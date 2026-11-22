"""A module for automatically fetching and composing SBEM objects."""

import logging
import uuid
from typing import Any, ClassVar, Literal, TypeVar, get_origin

import networkx as nx
import yaml
from pydantic import BaseModel, Field, create_model

from epinterface.sbem.common import NamedObject

logger = logging.getLogger(__name__)

"""Tree construction:

Every node in the tree may or may not have a selector action specified.
--> If it is specified, then we will select the deep tree for the requested compounded key from the datasource.  There will be options for if the key is not found ( e.g. fallbacks or raises.)
--> if it is specified, it will be loaded before it's children, but it's children (may) overwrite if specified.
--> If it is not specified, then it's children must be specified to avoid construction failure.

Branching:
Handle node, then handle its children.

Base case:
Start at root node.
"""


class ComponentNameConstructor(BaseModel, extra="forbid"):
    """A constructor for the name of a component. based off of a list of source fields."""

    source_fields: list[str] = Field(default_factory=list)
    prefix: str | None = None
    suffix: str | None = None

    def construct_name(self, x: dict[str, Any]) -> str:
        """Construct the name of a component based off of a dictionary of source fields."""
        for field in self.source_fields:
            if field not in x:
                # TODO: implement things like fallback values, e.g. if a field is not found, should we assume a value for that field?
                # should we silently fail?
                # should we warn? should we raise?
                msg = f"{field} is not in the source fields."
                raise ValueError(msg)
        core_name = "_".join(x[field] for field in self.source_fields)
        if self.prefix is not None:
            core_name = f"{self.prefix}_{core_name}"
        if self.suffix is not None:
            core_name = f"{core_name}_{self.suffix}"
        return core_name


NamedObjectT = TypeVar("NamedObjectT", bound=NamedObject)

# bind the Link type to a type where the first two type parameters are unknown but the third is a NamedObjectT


def construct_graph(root_node: type[NamedObject]):
    """Construct a graph of the SBEM objects.

    Nodes are fields of of SBEM NamedObjects, with edges representing the type of the child field as stored in the parent field.

    It begins with checking the root node's fields, then recurses into the child fields which are also NamedObjects.

    Note that currently, lists/dicts/tuples of NamedObjects are not supported.

    Args:
        root_node (type[NamedObject]): The root node of the graph.

    Returns:
        graph (nx.DiGraph): A graph of the SBEM objects.
    """
    g = nx.DiGraph()

    def handle_obj_class(g: nx.DiGraph, field_name: str, obj_class: type[NamedObject]):
        for child_field_name, child_annotation in obj_class.__annotations__.items():
            if isinstance(child_annotation, NamedObject.__class__) and issubclass(
                child_annotation, NamedObject
            ):
                g.add_edge(
                    field_name, child_field_name, data={"type": child_annotation}
                )
                handle_obj_class(g, child_field_name, child_annotation)

            elif hasattr(
                child_annotation, "__args__"
            ):  # but if it's a list, we want to skip
                if get_origin(child_annotation) in [list, tuple, dict]:
                    # TODO: special handling for list/dict cases using an additional entry in the edge data.
                    continue
                for note in child_annotation.__args__:
                    if isinstance(note, NamedObject.__class__) and issubclass(
                        note, NamedObject
                    ):
                        g.add_edge(field_name, child_field_name, data={"type": note})
                        handle_obj_class(g, child_field_name, note)
                        break

    handle_obj_class(g, "root", root_node)
    return g


def recursive_tree_dict_merge(d1: dict, d2: dict):
    """Merge two dictionaries recursively.

    The behavior is as follows:
    - Every key/tree in d2 is merged into d1.
    - If a key is found in both dictionaries, the value from d2 is used.
    - If a key is found in d1 but not in d2, the value from d1 is used.
    - If a key is found in d2 but not in d1, the value from d2 is used.

    Args:
        d1 (dict): The base dictionary.
        d2 (dict): The dictionary to merge.
    """
    for key, value in d2.items():
        if key not in d1:
            msg = f"{key} is not in the d1 target dictionary."
            raise ValueError(msg)
        if isinstance(value, dict):
            if not isinstance(d1[key], dict) and d1[key] is not None:
                msg = f"{key} is not a dict in the d1 target dictionary."
                raise ValueError(msg)
            recursive_tree_dict_merge(d1[key], value)
        else:
            d1[key] = value


class BaseResolutionTree(BaseModel):
    """A base class for Resolvers."""


def construct_composer_model(  # noqa: C901
    g: nx.DiGraph,
    root_validator: type[NamedObject],
    use_children: bool = True,
    extra_handling: Literal["ignore", "forbid"] = "forbid",
    allow_partials: bool = True,
):
    """Abstractly constructs a composition model from a graph of SBEM hierarchies.

    The ComposerModel.get_component(x: dict) method can be used to generate a composition of SBEM
    objects through the hierarchy, starting with the root node, and then substituting child nodes as they
    become available.

    Setting allow_partials to False will require a complete tree (but also use autopopulation) - this is mainly for easily generating schemas.

    Args:
        g (nx.DiGraph): The graph to construct the model from.
        root_validator (type[NamedObject]): The root validator type.
        use_children (bool): Whether to use `children` nesting keys (more verbose structure)
        extra_handling (Literal["ignore", "forbid"]): Whether to allow extra fields when validating provided serialized schemas.
        allow_partials (bool): Whether to allow partial resolutions.

    Returns:
        composer_model (BaseResolutionTree): A pydantic model that can be used to execute component mapping and composition.
    """
    from epinterface._optional import require

    require("prisma", "prisma", "Composing a model from the SBEM database")
    from prisma import Prisma

    from epinterface.sbem.prisma.client import deep_fetcher

    # Cache to avoid recomputing the same field types - e.g. once
    # we have computed the field type for a Occupancy.Schedule,
    # we can immediately return it for Lighting.Schedule, Thermostat.HeatingSchedule, etc.
    resolved_field_types = {}

    def get_field_type_for_edge(
        g: nx.DiGraph,
        target_node_name: str,  # TODO: this will cause infinite recursion when a parent and child have named fields in common.
        target_node_type: type[NamedObject],
        use_children: bool,
        allow_partials: bool,
    ):
        if target_node_type not in resolved_field_types:
            resolved_field_types[target_node_type] = handle_node(
                g,
                target_node_name,
                use_children,
                target_node_type,
                allow_partials=allow_partials,
            )
        return (
            (resolved_field_types[target_node_type] | None, None)
            if allow_partials
            else (
                resolved_field_types[target_node_type],
                resolved_field_types[target_node_type](selector=None),
            )
        )

    # TODO: figure out how to abstract this so that the root node type passed in can be used to
    # give type safety assurances on the selector.get_component() method..
    def handle_node(  # noqa: C901
        g: nx.DiGraph,
        node: str,
        use_children: bool,
        validator: type[NamedObject],
        allow_partials: bool,
    ):
        edges_starting_at_node = g.edges(node, data=True)
        node_fields = {}
        for _parent_name, child_name, data in edges_starting_at_node:
            node_fields[child_name] = get_field_type_for_edge(
                g,
                child_name,
                data["data"]["type"],
                use_children=use_children,
                allow_partials=allow_partials,
            )
        this_selector = (ComponentNameConstructor | None, None)

        # TODO: lift some of this scope up so we don't have a bunch of classes which are not part of the same
        # inheritance hierarchy.
        class ResolutionTreeWithValidator(BaseResolutionTree, extra=extra_handling):
            ValClass: ClassVar[type[NamedObject]] = validator
            selector: ComponentNameConstructor | None

            # TODO: we should allow fetching from in mem caches or other sources
            # so that this becomes abstracted and decoupled from the
            # database logic.
            @classmethod
            def get_deep_fetcher(cls):
                """Get the deep fetcher for the component corresponding to the selected validator."""
                return deep_fetcher.get_deep_fetcher(cls.ValClass)

            @classmethod
            def create_data_entry_template(cls):
                g = construct_graph(cls.ValClass)
                Model = construct_composer_model(
                    g,
                    root_validator=cls.ValClass,
                    use_children=False,
                    allow_partials=False,
                )
                model = Model(
                    selector=ComponentNameConstructor(
                        source_fields=["selector_col_a", "selector_col_b"]
                    )
                )

                return yaml.safe_dump(
                    model.model_dump(
                        exclude_none=True,
                    ),
                    indent=2,
                )

            def get_component(
                self,
                context: dict,
                allow_unvalidated: bool = False,
                db: Prisma | None = None,
                do_validate_resolution: bool = True,
            ):
                """Construct a component from the context dictionary, including executing subconstructions.

                Args:
                    context (dict): The context dictionary.
                    allow_unvalidated (bool): Whether to allow unvalidated components during construction - necessary for partial overwrites.
                    db (Prisma | None): The database to use.
                    do_validate_resolution (bool): Whether to validate that the resolution is guaranteed to return a component (assuming no db calls fail).  We skip this on children since they are allowed to be partial.

                Returns:
                    component (NamedObject): The constructed component.
                """
                self.validate_successful_resolution(do_validate_resolution)
                component_name = (
                    self.selector.construct_name(context)
                    if self.selector is not None
                    else None
                )
                children_components = {}
                for field_name in self.model_dump():
                    field_selector = getattr(self, field_name)
                    if (
                        # TODO: rewrite this check to use issubclass with BaseResolutionTree
                        # but BaseResolutionTree will need updating so that it is generic enough to include get_component
                        not isinstance(field_selector, ComponentNameConstructor)
                        and field_selector is not None
                    ):
                        children_components[field_name] = field_selector.get_component(
                            context=context,
                            allow_unvalidated=True,
                            db=db,
                            do_validate_resolution=False,
                        )

                if component_name is None:
                    component_name = f"{self.ValClass.__name__}_{str(uuid.uuid4())[:8]}"
                    try:
                        component = self.ValClass(
                            Name=component_name, **children_components
                        )
                    except Exception:
                        if allow_unvalidated:
                            return {"Name": component_name, **children_components}
                        else:
                            raise
                else:
                    fetcher = self.get_deep_fetcher()
                    _record, component_base = fetcher.get_deep_object(
                        component_name, db=db
                    )
                    data = component_base.model_dump(exclude_none=True)

                    recursive_tree_dict_merge(data, children_components)

                    component = self.ValClass(**data)
                return component

            def validate_successful_resolution(
                self, raise_on_failure: bool = True
            ) -> tuple[bool, list[str]]:
                """Validate that the tree will always resolve to a valid component.

                This is true if either (a) the selector is not None, or (b) all of its (required) children's successfully resolve,
                meaning we will use a recursive computation.


                Note: special handling is not yet implemented for the case where a child is nullable.

                Note: special handling will be required if/when non-deep keys (e.g. float params) become targetable.
                """
                # Children can be incomplete if parent is not specified.
                # so we circuit break if the parent has a selector.
                if self.selector is not None:
                    return True, []

                children_to_check = [
                    child for child in self.model_fields if child != "selector"
                ]
                if len(children_to_check) == 0:
                    # We are at a leaf node, which is only valid if it has a selector.
                    # TODO: in the future, leaf nodes could be constructed dynamically by assigning computers for field values.
                    return False, ["NoSelectorSpecified"]
                is_valid = True
                errors = []
                for child in children_to_check:
                    child_selector = getattr(self, child)
                    if child_selector is None:
                        is_valid = False
                        msg = f"{child}:NoSelectorSpecified"
                        errors.append(msg)
                        continue
                    if not issubclass(child_selector.__class__, BaseResolutionTree):
                        msg = f"{child}:UnexpectedNonSelector[{type(child_selector)}]"
                        is_valid = False
                        errors.append(msg)
                        continue
                    child_is_valid, child_errors = (
                        child_selector.validate_successful_resolution(
                            raise_on_failure=False
                        )
                    )
                    is_valid = is_valid and child_is_valid
                    errors.extend([f"{child}:{error}" for error in child_errors])

                if raise_on_failure and not is_valid:
                    raise ValueError("\n".join(errors))
                return is_valid, errors

        if use_children:
            children_model = create_model(
                f"{node}Selector",
                **node_fields,
            )

            return create_model(
                f"{node}Selector",
                children=(children_model | None, None),
                selector=this_selector,
                __base__=ResolutionTreeWithValidator,
            )
        else:
            # we want to add a classvar to the model which stores the validator

            return create_model(
                f"{node}Selector",
                **node_fields,
                selector=this_selector,
                __base__=ResolutionTreeWithValidator,
            )

    return handle_node(
        g,
        "root",
        use_children=use_children,
        validator=root_validator,
        allow_partials=allow_partials,
    )
