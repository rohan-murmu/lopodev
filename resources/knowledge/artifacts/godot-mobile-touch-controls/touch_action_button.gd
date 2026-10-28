class_name TouchActionButton
extends Control
## Multitouch-safe HUD button that presses an input action.
##
## Standard Buttons only see the first finger (via mouse emulation), so they
## stop working while the player holds the joystick. This control owns its
## own finger in _input and presses `action`, so it can be held together with
## movement and look. Draws a circle; replace _draw() or add children for art.

signal pressed_changed(is_pressed: bool)

@export var action: StringName = &"fire"
## Release the action if the finger slides off the button.
@export var release_on_exit := false
@export var idle_color := Color(1, 1, 1, 0.25)
@export var pressed_color := Color(1, 1, 1, 0.6)
@export var disabled := false:
	set(value):
		disabled = value
		if disabled:
			release()
		queue_redraw()

var finger := -1


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func is_pressed() -> bool:
	return finger != -1


func _input(event: InputEvent) -> void:
	if disabled or not is_visible_in_tree():
		return
	if event is InputEventScreenTouch:
		if event.pressed and finger == -1 and get_global_rect().has_point(event.position):
			finger = event.index
			if InputMap.has_action(action):
				Input.action_press(action)
			pressed_changed.emit(true)
			queue_redraw()
			get_viewport().set_input_as_handled()
		elif not event.pressed and event.index == finger:
			release()
			get_viewport().set_input_as_handled()
	elif event is InputEventScreenDrag and event.index == finger:
		if release_on_exit and not get_global_rect().has_point(event.position):
			release()
		get_viewport().set_input_as_handled()


func release() -> void:
	if finger == -1:
		return
	finger = -1
	if InputMap.has_action(action):
		Input.action_release(action)
	pressed_changed.emit(false)
	queue_redraw()


func _notification(what: int) -> void:
	match what:
		NOTIFICATION_PAUSED, NOTIFICATION_APPLICATION_FOCUS_OUT, \
		NOTIFICATION_APPLICATION_PAUSED, NOTIFICATION_EXIT_TREE:
			release()
		NOTIFICATION_VISIBILITY_CHANGED:
			if not is_visible_in_tree():
				release()


func _draw() -> void:
	var color := pressed_color if is_pressed() else idle_color
	if disabled:
		color = Color(color, color.a * 0.4)
	draw_circle(size / 2.0, minf(size.x, size.y) / 2.0, color)
