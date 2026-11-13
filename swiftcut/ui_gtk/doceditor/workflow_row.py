from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Gdk, Gio, Gtk

from ...context import get_context
from ...core.step_registry import step_registry
from ...core.undo.list_cmd import ListItemCommand, ReorderListCommand
from ..icons import get_icon
from ..layout import (
    COMPACT_SPACE_CONTROL,
    CONTROL_SIZE,
    ICON_GLYPH,
    icon_button,
    stylesheet,
)
from ..shared.gtk import apply_css
from ..shared.popover_menu import PopoverMenu
from .step_settings.dialog import StepSettingsDialog

if TYPE_CHECKING:
    from ...core.doc import Doc
    from ...core.layer import Layer
    from ...core.step import Step
    from ...core.workflow import Workflow
    from ...doceditor.editor import DocEditor

css = stylesheet("""
.workflow-row {
    min-height: $compact_row;
    padding: 0 $compact_space_control;
    margin-bottom: $compact_space_control;
    background-color: alpha(@theme_fg_color, 0.04);
    border-bottom: $hairline solid @borders;
}
.workflow-step-button {
    min-width: 0;
    min-height: 0;
    padding: 0;
    margin: 0;
    border-radius: $radius_cell;
}
.workflow-step-button:hover {
    background-color: alpha(@theme_fg_color, 0.08);
}
.workflow-arrow {
    margin: 0 -$hairline;
}
.workflow-drop-indicator {
    min-width: $stroke;
    min-height: $drop_indicator;
    background-color: @accent_color;
    border-radius: $radius_marker;
}
""")

_FALLBACK_ICON = "laser-path-symbolic"
_STEP_PAYLOAD_PREFIX = "step:"
_STEP_DRAG_ACTIONS = Gdk.DragAction.MOVE | Gdk.DragAction.COPY


def step_payload(workflow_uid: str, step_uid: str) -> str:
    """The drag payload of a step: its workflow's uid and its own."""
    return f"{_STEP_PAYLOAD_PREFIX}{workflow_uid}:{step_uid}"


def parse_step_payload(value) -> tuple[str, str] | None:
    """The (workflow uid, step uid) of a step payload, else None."""
    if not isinstance(value, str) or not value.startswith(
        _STEP_PAYLOAD_PREFIX
    ):
        return None
    uids = value[len(_STEP_PAYLOAD_PREFIX) :].split(":")
    if len(uids) != 2 or not all(uids):
        return None
    return uids[0], uids[1]


def find_step(doc: "Doc", uids: tuple[str, str]) -> "Step | None":
    """The step a parsed payload names in doc, else None."""
    workflow_uid, step_uid = uids
    for layer in doc.layers:
        workflow = layer.workflow
        if workflow is not None and workflow.uid == workflow_uid:
            return next((s for s in workflow.steps if s.uid == step_uid), None)
    return None


def drop_copies(drop_target: Gtk.DropTarget) -> bool:
    """
    Whether a step drop copies: the drop offers nothing but a copy.
    The platform narrows a move-or-copy drag to a copy while its copy
    key is held: Option on macOS, Ctrl on Windows and Linux. Drag
    events carry no modifier state, so the keys are not read here, and
    on Windows GDK makes an Alt drag a move.
    """
    drop = drop_target.get_current_drop()
    return drop is not None and drop.get_actions() == Gdk.DragAction.COPY


class WorkflowRow(Gtk.Box):
    #: The step being dragged from any row, from drag-begin to drag-end.
    dragged_step: "Step | None" = None

    def __init__(
        self,
        editor: "DocEditor",
        layer: "Layer",
    ):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        apply_css(css)
        self.add_css_class("workflow-row")
        self.set_hexpand(True)

        self.editor = editor
        self.layer = layer
        self._workflow: Workflow | None = None
        self._step_buttons: list = []
        self._btn_uids: dict = {}
        self._drop_indicator: Gtk.Box | None = None
        self._prepared_step: Step | None = None
        self._context_popover: Gtk.PopoverMenu | None = None
        self._context_step = None

        actions = Gio.SimpleActionGroup()
        delete_action = Gio.SimpleAction.new("delete", None)
        delete_action.connect("activate", self._on_delete_action)
        actions.add_action(delete_action)
        self.insert_action_group("step", actions)

        self._setup_drag_source()
        self._setup_drop_target()

        self._connect_machine()
        self._connect_workflow()
        self._rebuild()

        right_click = Gtk.GestureClick()
        right_click.set_button(Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", self._on_right_click_pressed)
        self.add_controller(right_click)

    def _setup_drag_source(self):
        self._drag_source = Gtk.DragSource()
        self._drag_source.set_actions(_STEP_DRAG_ACTIONS)
        self._drag_source.connect("prepare", self._on_drag_prepare)
        self._drag_source.connect("drag-begin", self._on_drag_begin)
        self._drag_source.connect("drag-end", self._on_drag_end)
        self._drag_source.connect("drag-cancel", self._on_drag_cancel)
        self._drag_source.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(self._drag_source)

    def _setup_drop_target(self):
        self._drop_target = Gtk.DropTarget.new(str, _STEP_DRAG_ACTIONS)
        self._drop_target.connect("drop", self._on_drop)
        self._drop_target.connect("motion", self._on_drop_motion)
        self._drop_target.connect("leave", self._on_drop_leave)
        self.add_controller(self._drop_target)

    def _connect_machine(self):
        machine = get_context().machine
        if machine:
            machine.changed.connect(self._on_machine_changed)

    def _disconnect_machine(self):
        machine = get_context().machine
        if machine:
            try:
                machine.changed.disconnect(self._on_machine_changed)
            except (TypeError, ValueError):
                pass

    def _on_machine_changed(self, sender, **kwargs):
        self._rebuild()

    def _connect_workflow(self):
        self._disconnect_workflow()
        self._workflow = self.layer.workflow
        if self._workflow:
            self._workflow.descendant_added.connect(self._on_workflow_changed)
            self._workflow.descendant_removed.connect(
                self._on_workflow_changed
            )
            self._workflow.descendant_updated.connect(
                self._on_workflow_changed
            )
            self._workflow.updated.connect(self._on_workflow_changed)

    def _disconnect_workflow(self):
        if not self._workflow:
            return
        try:
            self._workflow.descendant_added.disconnect(
                self._on_workflow_changed
            )
            self._workflow.descendant_removed.disconnect(
                self._on_workflow_changed
            )
            self._workflow.descendant_updated.disconnect(
                self._on_workflow_changed
            )
            self._workflow.updated.disconnect(self._on_workflow_changed)
        except (TypeError, ValueError):
            pass
        self._workflow = None

    def refresh(self):
        current_workflow = self.layer.workflow
        if current_workflow is not self._workflow:
            self._connect_workflow()
            self._rebuild()

    def _on_workflow_changed(self, sender, **kwargs):
        self._rebuild()

    def _get_step_icon(self, step) -> str:
        return step.ICON or _FALLBACK_ICON

    def _get_step_color(self, step) -> str | None:
        if not step.visible:
            return None
        machine = get_context().machine
        if not machine or not machine.heads:
            return None
        head = step.get_selected_head(machine)
        if head is None:
            return None
        return step.get_operation_color(head)

    def _apply_step_color(self, button: Gtk.Button, step):
        color = self._get_step_color(step)
        if not color:
            return
        class_name = f"step-color-{color.lstrip('#').lower()}"
        color_css = stylesheet(
            f".workflow-step-button.{class_name} {{"
            f"  border: $stroke solid {color};"
            "}"
        )
        apply_css(color_css)
        button.add_css_class(class_name)

    def _rebuild(self):
        self._drop_indicator = None
        self._step_buttons = []
        self._btn_uids = {}

        child = self.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.remove(child)
            child = next_child

        workflow = self._workflow
        if not workflow or not workflow.steps:
            label = Gtk.Label(label=_("No Operations"))
            label.add_css_class("dim-label")
            label.add_css_class("sc-caption")
            label.set_margin_start(COMPACT_SPACE_CONTROL)
            self.append(label)
        else:
            for i, step in enumerate(workflow.steps):
                if i > 0:
                    arrow = get_icon("go-next-symbolic")
                    arrow.add_css_class("workflow-arrow")
                    arrow.set_valign(Gtk.Align.CENTER)
                    self.append(arrow)

                icon = get_icon(self._get_step_icon(step))
                icon.set_pixel_size(ICON_GLYPH)

                button = Gtk.Button(child=icon)
                button.add_css_class("workflow-step-button")
                # The step's colour border sits inside the control size.
                button.set_size_request(CONTROL_SIZE, CONTROL_SIZE)
                button.add_css_class("flat")
                button.set_tooltip_text(step.name)
                button.set_valign(Gtk.Align.CENTER)
                button.connect(
                    "clicked", self._make_step_clicked_handler(step)
                )
                self._apply_step_color(button, step)
                self._btn_uids[id(button)] = step.uid
                self._step_buttons.append(button)
                self.append(button)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.append(spacer)

        add_btn = icon_button("add-symbolic", _("Add Step"))
        add_btn.connect("clicked", self._on_add_step_clicked)
        self.append(add_btn)

    def _step_uid_at(self, x: float) -> str | None:
        for btn in self._step_buttons:
            alloc = btn.get_allocation()
            if alloc.x <= x < alloc.x + alloc.width:
                return self._btn_uids.get(id(btn))
        return None

    def _btn_at(self, x: float) -> Gtk.Button | None:
        for btn in self._step_buttons:
            alloc = btn.get_allocation()
            if alloc.x <= x < alloc.x + alloc.width:
                return btn
        return None

    def _step_index_at(self, x: float) -> int:
        for i, btn in enumerate(self._step_buttons):
            alloc = btn.get_allocation()
            if x < alloc.x + alloc.width / 2:
                return i
        return len(self._step_buttons)

    def _on_drag_prepare(self, source, x, y):
        uid = self._step_uid_at(x)
        workflow = self._workflow
        if not uid or not workflow:
            return None
        step = next((s for s in workflow.steps if s.uid == uid), None)
        if step is None:
            return None

        btn = self._btn_at(x)
        if btn:
            snapshot = Gtk.Snapshot()
            Gtk.Widget.do_snapshot(btn, snapshot)
            paintable = snapshot.to_paintable()
            if paintable:
                btn_alloc = btn.get_allocation()
                source.set_icon(
                    paintable, btn_alloc.width / 2, btn_alloc.height / 2
                )

        self._prepared_step = step
        return Gdk.ContentProvider.new_for_value(
            step_payload(workflow.uid, uid)
        )

    def _on_drag_begin(self, source, drag):
        # Only a drag that began gets a drag-end or a drag-cancel.
        WorkflowRow.dragged_step = self._prepared_step
        self._prepared_step = None

    def _on_drag_end(self, source, drag, delete_data):
        WorkflowRow.dragged_step = None
        self._remove_drop_indicator()

    def _on_drag_cancel(self, source, drag, reason):
        WorkflowRow.dragged_step = None
        self._remove_drop_indicator()
        return False

    def _on_drop(self, drop_target, value, x, y):
        index = self._step_index_at(x)
        copy = drop_copies(drop_target)
        self._remove_drop_indicator()
        uids = parse_step_payload(value)
        step = find_step(self.editor.doc, uids) if uids else None
        if step is None or not self.layer.visible:
            return False
        moved = self.editor.layer.move_step_to_layer(
            step, self.layer, index, copy=copy
        )
        return moved is not None

    def _on_drop_motion(self, drop_target, x, y):
        if WorkflowRow.dragged_step is None or not self.layer.visible:
            self._remove_drop_indicator()
            return Gdk.DragAction(0)
        self._show_drop_indicator(self._step_index_at(x))
        copy = drop_copies(drop_target)
        return Gdk.DragAction.COPY if copy else Gdk.DragAction.MOVE

    def _on_drop_leave(self, drop_target):
        self._remove_drop_indicator()

    def _show_drop_indicator(self, index: int):
        self._remove_drop_indicator()
        if index < 0:
            return
        indicator = Gtk.Box()
        indicator.add_css_class("workflow-drop-indicator")
        indicator.set_valign(Gtk.Align.CENTER)
        self._drop_indicator = indicator
        if index >= len(self._step_buttons):
            last_btn = self._step_buttons[-1] if self._step_buttons else None
            if last_btn:
                self.insert_child_after(indicator, last_btn)
            else:
                self.prepend(indicator)
        else:
            btn = self._step_buttons[index]
            prev = btn.get_prev_sibling()
            if prev:
                self.insert_child_after(indicator, prev)
            else:
                self.prepend(indicator)

    def _remove_drop_indicator(self):
        if self._drop_indicator:
            self.remove(self._drop_indicator)
            self._drop_indicator = None

    def _make_step_clicked_handler(self, step):
        def handler(button):
            StepSettingsDialog.present_for_step(
                self.editor, step, self.get_root()
            )

        return handler

    def _on_add_step_clicked(self, button):
        workflow = self._workflow
        if not workflow or not workflow.doc:
            return
        machine = self.editor.context.machine
        popup = PopoverMenu(
            step_factories=step_registry.get_factories(
                machine.get_capabilities() if machine else None
            ),
            context=self.editor.context,
        )
        popup.set_parent(self)
        popup.popup()
        popup.connect("closed", self._on_add_step_dialog_response)

    def _on_add_step_dialog_response(self, popup):
        workflow = self._workflow
        if not workflow or not workflow.doc:
            return
        if popup.selected_item:
            step_factory = popup.selected_item
            new_step = step_factory(self.editor.context)
            name = _("Add step '{name}'").format(name=new_step.name)
            # One undo entry for the step and its layer's recipe color.
            with workflow.doc.history_manager.transaction(name):
                self.editor.step.apply_best_recipe_to_step(
                    new_step, layer=self.layer
                )
                command = ListItemCommand(
                    owner_obj=workflow,
                    item=new_step,
                    undo_command="remove_step",
                    redo_command="add_step",
                    name=name,
                )
                workflow.doc.history_manager.execute(command)
            StepSettingsDialog.present_for_step(
                self.editor, new_step, self.get_root()
            )

    def _on_right_click_pressed(self, gesture, n_press, x, y):
        uid = self._step_uid_at(x)
        workflow = self._workflow
        if not uid or not workflow:
            return
        step = next((s for s in workflow.steps if s.uid == uid), None)
        if step is None:
            return
        self._context_step = step
        menu = Gio.Menu.new()
        menu.append_item(Gio.MenuItem.new(_("Delete"), "step.delete"))
        self._popup_context_menu(menu, gesture)

    def _popup_context_menu(self, menu: Gio.Menu, gesture: Gtk.Gesture):
        if self._context_popover:
            self._context_popover.unparent()
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self)
        popover.set_has_arrow(False)
        ok, rect = gesture.get_bounding_box()
        if ok:
            popover.set_pointing_to(rect)
        self._context_popover = popover
        popover.popup()

    def _on_delete_action(self, action, param):
        workflow = self._workflow
        step = self._context_step
        if not workflow or not workflow.doc or step is None:
            return
        new_list = [s for s in workflow.steps if s is not step]
        command = ReorderListCommand(
            target_obj=workflow,
            list_property_name="steps",
            new_list=new_list,
            setter_method_name="set_steps",
            name=_("Remove step '{name}'").format(name=step.name),
        )
        workflow.doc.history_manager.execute(command)

    def do_destroy(self):
        self._disconnect_machine()
        self._disconnect_workflow()
