from __future__ import annotations

import logging
from gettext import gettext as _
from gettext import ngettext
from typing import TYPE_CHECKING, Any

from ..core.color_preset import get_color_preset_mgr
from ..core.step_registry import step_registry
from ..core.undo import ChangePropertyCommand, DictItemCommand
from ..core.vectorization_spec import LayerSource, PassthroughSpec

if TYPE_CHECKING:
    from ..core.layer import Layer
    from ..core.recipe import Recipe
    from ..core.step import Step
    from .editor import DocEditor


logger = logging.getLogger(__name__)


class StepCmd:
    """Handles commands related to step settings."""

    def __init__(self, editor: DocEditor):
        self._editor = editor
        self._doc = editor.doc
        self._context = editor.context

    def set_step_param(
        self,
        target_dict: dict[str, Any],
        key: str,
        new_value: Any,
        name: str,
        on_change_callback: Any = None,
    ):
        """
        Sets a parameter in a step's dictionary with an undoable command.

        Args:
            target_dict: The dictionary to modify.
            key: The key of the parameter to set.
            new_value: The new value for the parameter.
            name: The name of the command for the undo stack.
            on_change_callback: A callback to execute after the command.
        """
        # Check if the value is a float and compare with a tolerance
        if isinstance(new_value, float):
            old_value = target_dict.get(key)
            if old_value is None:
                pass
            elif (
                isinstance(old_value, (int, float))
                and abs(new_value - old_value) < 1e-6
            ):
                return
        elif new_value == target_dict.get(key):
            return

        command = DictItemCommand(
            target_dict=target_dict,
            key=key,
            new_value=new_value,
            name=name,
            on_change_callback=on_change_callback,
        )
        self._editor.history_manager.execute(command)

    def apply_best_recipe_to_step(
        self, step: Step, layer: Layer | None = None
    ):
        """
        Finds the best matching recipe for a given step and applies its
        settings. This modifies the step object directly and is not undoable
        by itself; it should be called before the step is added to the
        document via an undoable command.

        If a layer is given and the recipe has a color, the layer takes
        that color through an undoable command. A layer with a picked
        material gives the step that material's recipe, if it has one.
        """
        # Get the stock items from the document
        stock_items = self._doc.stock_items
        machine = self._context.machine

        # Query the RecipeManager for the best match for this step type.
        matching_recipes: list = []
        recipe_mgr = self._context.recipe_mgr
        material_recipe = (
            self._material_recipe(layer.material, step)
            if layer is not None and layer.material is not None
            else None
        )
        if material_recipe is not None:
            matching_recipes = [material_recipe]
        elif recipe_mgr is not None:
            matching_recipes = recipe_mgr.find_recipes(
                stock_items=stock_items,
                machine=machine,
                step_type=type(step).__name__,
            )

        # If matching_recipes is not empty, apply the best one
        if matching_recipes:
            best_recipe = matching_recipes[0]
            logger.info(
                f"Applying best recipe '{best_recipe.name}' to new step."
            )
            self._fill_step(step, best_recipe)

            if (
                layer is not None
                and best_recipe.color
                and best_recipe.color != layer.color
            ):
                self._editor.history_manager.execute(
                    ChangePropertyCommand(
                        target=layer,
                        property_name="color",
                        new_value=best_recipe.color,
                        setter_method_name="set_color",
                        name=_("Set layer color"),
                    )
                )

    def _fill_step(self, step: Step, recipe: Recipe) -> None:
        """
        Applies a recipe to a step directly, not undoably: its settings
        for the active machine, its transformer settings and its uid.
        """
        # Apply the settings to the step object
        for key, value in recipe.settings_for(self._context.machine).items():
            if hasattr(step, key):
                setattr(step, key, value)

        # Apply transformer settings directly to the step. Per-workpiece
        # and per-step dicts are mutated in place.
        self._apply_recipe_transformers_to_step(step, recipe)

        # Store a reference to the applied recipe
        step.applied_recipe_uid = recipe.uid

    def apply_recipe(self, step: Step, recipe: Recipe, transaction: Any):
        """
        Applies a recipe to a step inside a history transaction: its
        uid, its settings for the active machine and its transformer
        settings. The layer color is left to the caller.
        """

        def send_updated():
            step.updated.send(step)

        transaction.execute(
            ChangePropertyCommand(
                target=step,
                property_name="applied_recipe_uid",
                new_value=recipe.uid,
                on_change_callback=send_updated,
            )
        )
        # Set each setting the recipe carries; skip keys this step
        # does not own.
        for key, value in recipe.settings_for(self._context.machine).items():
            if not hasattr(step, key):
                continue
            transaction.execute(
                ChangePropertyCommand(
                    target=step,
                    property_name=key,
                    new_value=value,
                    on_change_callback=send_updated,
                )
            )
        # Apply transformer settings: for each recipe transformer with
        # recipe_apply=True, find the step's matching dict by name and
        # overwrite its params with undoable commands.
        self._apply_recipe_transformers(step, recipe.transformer_dicts)

    def _apply_recipe_transformers(
        self, step: Step, transformer_dicts: list[dict[str, Any]]
    ) -> None:
        """Apply recipe transformer settings to the step's transformers.

        For each recipe dict with ``recipe_apply=True``, find the
        matching step dict by ``name`` (searching
        ``per_step_transformers_dicts`` first, then
        ``per_workpiece_transformers_dicts``). For each param key
        (except ``name`` and ``recipe_apply``), emit an undoable
        ``set_step_param`` command. The appropriate step callback
        matches the step-mode post-processing page's logic.
        """
        step_dicts_by_name: dict[str, dict[str, Any]] = {}
        for d in list(step.per_step_transformers_dicts) + list(
            step.per_workpiece_transformers_dicts
        ):
            name = d.get("name")
            if name and name not in step_dicts_by_name:
                step_dicts_by_name[name] = d

        for recipe_dict in transformer_dicts or []:
            if not recipe_dict.get("recipe_apply", True):
                continue
            name = recipe_dict.get("name")
            if not name:
                continue
            step_dict = step_dicts_by_name.get(name)
            if step_dict is None:
                continue
            is_per_step = step_dict in (step.per_step_transformers_dicts)
            callback = (
                step.per_step_transformer_changed.send
                if is_per_step
                else lambda: step.updated.send(step)
            )
            for key, value in recipe_dict.items():
                if key in ("name", "recipe_apply"):
                    continue
                self.set_step_param(
                    target_dict=step_dict,
                    key=key,
                    new_value=value,
                    name=_("Apply Recipe Transformer"),
                    on_change_callback=callback,
                )

    def apply_material(self, layer: Layer, material: tuple[str, float] | None):
        """
        Picks a material for a layer, in one undo step. Each of its
        steps takes the settings of the material's recipe for its type
        on the active machine, the layer records that machine as the one
        its steps were filled for, and it takes the color of the first
        recipe applied that has one. A step the material has no recipe
        for keeps its settings, and a notification names it. None
        ("Manual") forgets the material and leaves the steps as they
        are.
        """
        if material == layer.material:
            return
        machine = self._context.machine
        unchanged = []
        with self._editor.history_manager.transaction(
            _("Set layer material")
        ) as t:
            t.execute(
                ChangePropertyCommand(
                    target=layer,
                    property_name="material",
                    new_value=material,
                    setter_method_name="set_material",
                )
            )
            t.execute(
                ChangePropertyCommand(
                    target=layer,
                    property_name="material_machine",
                    new_value=machine.name if material and machine else None,
                )
            )
            color = None
            for step, recipe in self._material_recipes(layer):
                if recipe is None:
                    unchanged.append(step.name)
                    continue
                self.apply_recipe(step, recipe, t)
                color = color or recipe.color
            if color:
                t.execute(
                    ChangePropertyCommand(
                        target=layer,
                        property_name="color",
                        new_value=color,
                        setter_method_name="set_color",
                    )
                )
        if unchanged:
            self._editor.notification_requested.send(
                self,
                message=ngettext(
                    "This material has no recipe for {steps}; its "
                    "settings stay as they were.",
                    "This material has no recipe for {steps}; their "
                    "settings stay as they were.",
                    len(unchanged),
                ).format(steps=", ".join(unchanged)),
            )

    def refill_layer_materials(self):
        """
        Fills the steps of every layer whose material was filled for
        another machine than the active one, or for an unknown one,
        from that material's recipes for the active machine, and
        records the active machine on the layer: after a machine
        switch, an undo or redo, and when a document is set. Applied
        directly, outside the undo history; edits made by hand on such
        a layer are overwritten.
        """
        machine = self._context.machine
        if machine is None:
            return
        for layer in self._editor.doc.layers:
            if layer.material is None:
                continue
            if layer.material_machine == machine.name:
                continue
            layer.material_machine = machine.name
            for step, recipe in self._material_recipes(layer):
                if recipe is not None:
                    self._refill_step(step, recipe)

    def _refill_step(self, step: Step, recipe: Recipe) -> None:
        """
        Fills a step directly and sends what the undoable apply sends
        for what changed: the step's updated signal, and its per-step
        transformer signal when a per-step transformer changed. A step
        that is already filled so sends nothing.
        """
        keys = [
            key
            for key in recipe.settings_for(self._context.machine)
            if hasattr(step, key)
        ]

        def state():
            return (
                [getattr(step, key) for key in keys],
                step.applied_recipe_uid,
                [dict(d) for d in step.per_workpiece_transformers_dicts],
                [dict(d) for d in step.per_step_transformers_dicts],
            )

        before = state()
        self._fill_step(step, recipe)
        after = state()
        if after != before:
            step.updated.send(step)
        if after[3] != before[3]:
            step.per_step_transformer_changed.send()

    def _material_recipes(
        self, layer: Layer
    ) -> list[tuple[Step, Recipe | None]]:
        """
        The layer's steps, each with its recipe for the layer's
        material on the active machine, or None if it has none.
        """
        material = layer.material
        if material is None or layer.workflow is None:
            return []
        return [
            (step, self._material_recipe(material, step))
            for step in layer.workflow.steps
        ]

    def _material_recipe(
        self, material: tuple[str, float], step: Step
    ) -> Recipe | None:
        """The recipe for a material and a step's type, or None."""
        uid, thickness = material
        return self._context.recipe_mgr.find_material_recipe(
            uid,
            thickness,
            self._context.machine,
            step_type=type(step).__name__,
        )

    @staticmethod
    def _apply_recipe_transformers_to_step(step: Step, recipe: Recipe) -> None:
        """Apply a recipe's transformer settings to a fresh step.

        Direct mutation of the step's per-workpiece and per-step
        transformer dicts, used by the auto-apply path. For each recipe
        transformer dict with ``recipe_apply=True``, update the step's
        matching dict (by name) with ``enabled`` and the transformer's
        params.
        """
        step_dicts_by_name: dict[str, dict] = {}
        for d in list(step.per_workpiece_transformers_dicts) + list(
            step.per_step_transformers_dicts
        ):
            name = d.get("name")
            if name and name not in step_dicts_by_name:
                step_dicts_by_name[name] = d

        for recipe_dict in recipe.transformer_dicts or []:
            if not recipe_dict.get("recipe_apply", True):
                continue
            name = recipe_dict.get("name")
            if not name:
                continue
            step_dict = step_dicts_by_name.get(name)
            if step_dict is None:
                continue
            for key, value in recipe_dict.items():
                if key in ("name", "recipe_apply"):
                    continue
                step_dict[key] = value

    def rename_step(self, step: Step, new_name: str):
        """Renames a step with an undoable command."""
        if new_name == step.name:
            return
        cmd = ChangePropertyCommand(
            target=step,
            property_name="name",
            new_value=new_name,
            setter_method_name="set_name",
            name=_("Rename step"),
        )
        self._editor.history_manager.execute(cmd)

    def initialize_default_steps(self):
        """
        Adds a default Contour step to the first layer if it has no steps.

        Called on application startup or when a new empty document is created.
        """
        doc = self._doc
        if not doc.layers:
            return

        first_layer = doc.layers[0]
        workflow = first_layer.workflow
        if not workflow or workflow.has_steps():
            return

        contour_cls = step_registry.get("ContourStep")
        if not contour_cls:
            return

        step = contour_cls.create(self._context)
        self.apply_best_recipe_to_step(step)
        workflow.add_step(step)
        logger.info(
            f"Added default '{step.typelabel}' step to "
            f"layer '{first_layer.name}'."
        )

    def add_default_steps_for_layers(self, layers):
        """
        Adds default steps to newly imported layers.

        For each layer:
        - If it was imported from a color source whose color matches a
          color rule, a step of the rule's step type is created. If that
          step type is not registered (e.g. its addon was uninstalled),
          it falls back to the default behavior below and logs a
          warning.
        - If workpieces have fills: add Contour + Engrave steps
        - If workpieces have only unfilled vectors: add Contour only
        """
        contour_cls = step_registry.get("ContourStep")
        engrave_cls = step_registry.get("EngraveStep")

        for layer in layers:
            workflow = layer.workflow
            if not workflow or workflow.has_steps():
                continue

            rule_cls = self._step_class_from_color_rule(layer)
            if rule_cls is not None:
                step = rule_cls.create(self._context)
                self.apply_best_recipe_to_step(step)
                workflow.add_step(step)
                logger.info(
                    f"Added default '{step.typelabel}' step to "
                    f"layer '{layer.name}' (color rule)."
                )
                continue

            if contour_cls:
                step = contour_cls.create(self._context)
                self.apply_best_recipe_to_step(step)
                workflow.add_step(step)
                logger.info(
                    f"Added default '{step.typelabel}' step to "
                    f"layer '{layer.name}'."
                )

            if layer.has_fills and engrave_cls:
                step = engrave_cls.create(self._context)
                self.apply_best_recipe_to_step(step)
                workflow.add_step(step)
                logger.info(
                    f"Added default '{step.typelabel}' step to "
                    f"layer '{layer.name}' (has fills)."
                )

    def _step_class_from_color_rule(self, layer) -> type[Step] | None:
        """
        Resolve the step class a color rule maps to for a layer.

        Inspects each workpiece's source segment: for color-source
        imports the segment's ``layer_id`` is the resolved SVG color, so
        the rule applies regardless of whether the workpiece was placed
        on a fresh layer (which carries the color) or an existing one
        (which does not). Returns the step class of the first matching
        rule, or ``None`` when no rule applies. If a rule matches but
        its step type is no longer registered, a warning is logged and
        ``None`` is returned so the caller falls back to the default
        behavior.
        """
        for workpiece in layer.all_workpieces:
            segment = workpiece.source_segment
            if segment is None:
                continue
            spec = segment.vectorization_spec
            if not (
                isinstance(spec, PassthroughSpec)
                and spec.layer_source == LayerSource.COLORS
            ):
                continue
            color = segment.layer_id
            if not color:
                continue
            preset = get_color_preset_mgr().get_preset(color)
            if preset is None:
                logger.debug(
                    f"No color rule for layer '{layer.name}' (color {color})."
                )
                continue
            cls = step_registry.get(preset.step_type)
            if cls is None:
                logger.warning(
                    f"Step type '{preset.step_type}' from a color rule "
                    f"is not registered; falling back to default steps "
                    f"for layer '{layer.name}'."
                )
                return None
            return cls
        return None
