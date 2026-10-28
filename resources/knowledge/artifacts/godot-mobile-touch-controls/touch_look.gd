class_name TouchLook
extends Control
## Drag-to-look region for first/third-person cameras.
##
## Receives touches through _gui_input: Godot 4 routes each finger's drags
## to the control it pressed, so ownership is per finger. Joysticks and
## action buttons claim their fingers earlier, in _input, so they always win.
## Do not move this to _unhandled_input: a full-rect HUD Control with the
## default MOUSE_FILTER_STOP consumes touches before that stage.
## Read the accumulated rotation once per frame with consume_look().

signal looked(delta: Vector2)

## Radians per pixel of drag.
@export var sensitivity := 0.006
@export var invert_y := false

var finger := -1
var _pending := Vector2.ZERO


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP


func _gui_input(event: InputEvent) -> void:
	if event is InputEventScreenTouch:
		if event.pressed and finger == -1:
			finger = event.index
			accept_event()
		elif not event.pressed and event.index == finger:
			finger = -1
			accept_event()
	elif event is InputEventScreenDrag and event.index == finger:
		var delta: Vector2 = event.relative * sensitivity
		if invert_y:
			delta.y = -delta.y
		_pending += delta
		looked.emit(delta)
		accept_event()


## Returns rotation accumulated since the last call (x = yaw, y = pitch).
func consume_look() -> Vector2:
	var value := _pending
	_pending = Vector2.ZERO
	return value


func _notification(what: int) -> void:
	match what:
		NOTIFICATION_PAUSED, NOTIFICATION_APPLICATION_FOCUS_OUT, \
		NOTIFICATION_APPLICATION_PAUSED, NOTIFICATION_EXIT_TREE:
			finger = -1
			_pending = Vector2.ZERO
		NOTIFICATION_VISIBILITY_CHANGED:
			if not is_visible_in_tree():
				finger = -1
				_pending = Vector2.ZERO
