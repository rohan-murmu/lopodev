class_name VirtualJoystick
extends Control
## On-screen joystick that owns exactly one finger at a time.
##
## Touches are read in _input with explicit finger ownership, so the joystick
## keeps working while other fingers aim, fire or press HUD buttons. It
## presses the configured input actions with analog strength, so gameplay
## code keeps using Input.get_vector() and works the same with a keyboard.

signal moved(vector: Vector2)
signal released

@export var radius := 110.0
@export_range(0.0, 0.9) var deadzone := 0.15
@export var action_left: StringName = &"move_left"
@export var action_right: StringName = &"move_right"
@export var action_up: StringName = &"move_up"
@export var action_down: StringName = &"move_down"
## When true the stick centers where the finger lands inside this control.
@export var floating := true
@export var base_color := Color(1, 1, 1, 0.18)
@export var knob_color := Color(1, 1, 1, 0.55)

var finger := -1
var origin := Vector2.ZERO
var vector := Vector2.ZERO


func _ready() -> void:
	# Touches are handled in _input; ignoring mouse keeps emulated clicks
	# from reaching controls underneath with a stale position.
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _input(event: InputEvent) -> void:
	if not is_visible_in_tree():
		return
	if event is InputEventScreenTouch:
		if event.pressed and finger == -1 and get_global_rect().has_point(event.position):
			finger = event.index
			origin = event.position if floating else get_global_rect().get_center()
			_update(event.position)
			get_viewport().set_input_as_handled()
		elif not event.pressed and event.index == finger:
			release()
			get_viewport().set_input_as_handled()
	elif event is InputEventScreenDrag and event.index == finger:
		_update(event.position)
		get_viewport().set_input_as_handled()


func _update(position: Vector2) -> void:
	var raw := (position - origin).limit_length(radius) / radius
	var length := raw.length()
	vector = Vector2.ZERO if length < deadzone else raw / length * inverse_lerp(deadzone, 1.0, length)
	_apply_actions()
	moved.emit(vector)
	queue_redraw()


## Drops the finger and releases every action. Safe to call repeatedly.
func release() -> void:
	var was_active := finger != -1 or vector != Vector2.ZERO
	finger = -1
	vector = Vector2.ZERO
	_apply_actions()
	if was_active:
		released.emit()
	queue_redraw()


func _apply_actions() -> void:
	_set_action(action_left, maxf(-vector.x, 0.0))
	_set_action(action_right, maxf(vector.x, 0.0))
	_set_action(action_up, maxf(-vector.y, 0.0))
	_set_action(action_down, maxf(vector.y, 0.0))


func _set_action(action: StringName, strength: float) -> void:
	if action == &"" or not InputMap.has_action(action):
		return
	if strength > 0.0:
		Input.action_press(action, strength)
	else:
		Input.action_release(action)


func _notification(what: int) -> void:
	# A finger lifted while paused, hidden or backgrounded never sends its
	# release event to us; drop it so the player does not keep walking.
	match what:
		NOTIFICATION_PAUSED, NOTIFICATION_APPLICATION_FOCUS_OUT, \
		NOTIFICATION_APPLICATION_PAUSED, NOTIFICATION_EXIT_TREE:
			release()
		NOTIFICATION_VISIBILITY_CHANGED:
			if not is_visible_in_tree():
				release()


func _draw() -> void:
	var center := origin - global_position if finger != -1 else size / 2.0
	draw_circle(center, radius, base_color)
	draw_circle(center + vector * radius, radius * 0.4, knob_color)
