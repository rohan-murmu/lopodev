extends SceneTree
## Multitouch contract for the mobile touch-controls kit, driven by real
## InputEventScreenTouch/Drag events pushed through the root viewport.

const VirtualJoystick := preload("res://kit/virtual_joystick.gd")
const TouchLook := preload("res://kit/touch_look.gd")
const TouchActionButton := preload("res://kit/touch_action_button.gd")

var failures: Array[String] = []


func _initialize() -> void:
	_run.call_deferred()


func check(condition: bool, message: String) -> void:
	if condition:
		print("ok: " + message)
	else:
		failures.append(message)
		printerr("FAIL: " + message)


func touch(index: int, position: Vector2, pressed: bool) -> void:
	var event := InputEventScreenTouch.new()
	event.index = index
	event.position = position
	event.pressed = pressed
	root.push_input(event)


func drag(index: int, position: Vector2, relative: Vector2) -> void:
	var event := InputEventScreenDrag.new()
	event.index = index
	event.position = position
	event.relative = relative
	root.push_input(event)


func _run() -> void:
	for action in [&"move_left", &"move_right", &"move_up", &"move_down", &"fire"]:
		InputMap.add_action(action)
	# Headless defaults to a 100x100 window; test at a phone landscape size.
	root.size = Vector2i(1280, 720)
	await process_frame
	var size := root.get_visible_rect().size
	check(size == Vector2(1280, 720), "test viewport is 1280x720 (%s)" % size)
	var hud := Control.new()
	hud.size = size
	root.add_child(hud)

	var joystick: Control = VirtualJoystick.new()
	joystick.position = Vector2(0, size.y * 0.4)
	joystick.size = Vector2(size.x * 0.35, size.y * 0.6)
	joystick.radius = 100.0
	hud.add_child(joystick)

	var look: Control = TouchLook.new()
	look.position = Vector2(size.x * 0.4, 0)
	look.size = Vector2(size.x * 0.6, size.y)
	look.sensitivity = 0.01
	hud.add_child(look)

	# Deliberately inside the look region: the button must win its finger.
	var fire: Control = TouchActionButton.new()
	fire.position = Vector2(size.x - 160, size.y - 160)
	fire.size = Vector2(120, 120)
	hud.add_child(fire)
	await process_frame

	var stick_at := joystick.global_position + Vector2(150, 150)
	var look_at := look.global_position + Vector2(100, 100)
	var fire_at := fire.global_position + fire.size / 2.0

	# Finger 0 moves.
	touch(0, stick_at, true)
	drag(0, stick_at + Vector2(100, 0), Vector2(100, 0))
	check(joystick.finger == 0, "joystick owns finger 0")
	check(joystick.vector.x > 0.99 and absf(joystick.vector.y) < 0.01, "full right deflection -> x=1")
	check(Input.get_action_strength(&"move_right") > 0.99, "move_right pressed at full strength")
	check(Input.get_vector(&"move_left", &"move_right", &"move_up", &"move_down").x > 0.99,
			"gameplay Input.get_vector sees joystick")

	# Finger 1 looks while finger 0 keeps moving.
	touch(1, look_at, true)
	drag(1, look_at + Vector2(40, -20), Vector2(40, -20))
	var looked: Vector2 = look.consume_look()
	check(look.finger == 1, "touch-look owns finger 1")
	check(looked.is_equal_approx(Vector2(0.4, -0.2)), "look delta = relative * sensitivity (%s)" % looked)
	check(joystick.vector.x > 0.99, "joystick unaffected by look finger")
	check(look.consume_look() == Vector2.ZERO, "consume_look resets")

	# Finger 2 fires on a button that overlaps the look region.
	touch(2, fire_at, true)
	check(fire.is_pressed() and Input.is_action_pressed(&"fire"), "fire button claims finger 2 over look area")
	check(look.finger == 1, "look did not steal the button finger")
	drag(2, fire_at + Vector2(5, 5), Vector2(5, 5))
	check(look.consume_look() == Vector2.ZERO, "button finger drag does not rotate camera")
	touch(2, fire_at, false)
	check(not Input.is_action_pressed(&"fire"), "fire released with its finger")
	check(Input.get_action_strength(&"move_right") > 0.99, "movement still held after fire release")

	# A second finger inside the busy joystick zone is not stolen.
	touch(3, stick_at + Vector2(20, 20), true)
	check(joystick.finger == 0, "busy joystick ignores another finger")
	drag(3, stick_at + Vector2(-80, 20), Vector2(-100, 0))
	check(joystick.vector.x > 0.99, "foreign finger drag does not move joystick")
	touch(3, stick_at, false)

	# Deadzone.
	drag(0, stick_at + Vector2(5, 0), Vector2(-95, 0))
	check(joystick.vector == Vector2.ZERO, "inside deadzone -> zero vector")
	check(not Input.is_action_pressed(&"move_right"), "deadzone releases actions")

	# Diagonal half deflection keeps direction and scales strength.
	drag(0, stick_at + Vector2(-40, 40), Vector2(-45, 40))
	check(joystick.vector.x < 0.0 and joystick.vector.y > 0.0, "diagonal direction preserved")
	check(joystick.vector.length() < 1.0, "partial deflection < 1")

	touch(0, stick_at, false)
	check(joystick.finger == -1 and joystick.vector == Vector2.ZERO, "release clears joystick")
	check(not Input.is_action_pressed(&"move_left") and not Input.is_action_pressed(&"move_down"),
			"release clears actions")
	touch(1, look_at, false)
	check(look.finger == -1, "look releases finger 1")

	# Pausing while held must not leave stale input.
	touch(0, stick_at, true)
	drag(0, stick_at + Vector2(0, -100), Vector2(0, -100))
	touch(2, fire_at, true)
	check(Input.is_action_pressed(&"move_up") and Input.is_action_pressed(&"fire"), "held before pause")
	paused = true
	await process_frame
	check(not Input.is_action_pressed(&"move_up"), "pause releases movement")
	check(not Input.is_action_pressed(&"fire"), "pause releases fire")
	touch(0, stick_at, true)
	check(joystick.finger == -1, "paused joystick ignores touches")
	paused = false
	await process_frame

	# Focus loss (app switched away mid-touch).
	touch(5, stick_at, true)
	drag(5, stick_at + Vector2(100, 0), Vector2(100, 0))
	joystick.notification(Node.NOTIFICATION_APPLICATION_FOCUS_OUT)
	check(joystick.finger == -1 and not Input.is_action_pressed(&"move_right"), "focus loss releases joystick")

	# Hidden controls release and ignore input.
	touch(6, fire_at, true)
	fire.hide()
	check(not Input.is_action_pressed(&"fire"), "hiding the button releases its action")
	fire.show()
	fire.disabled = true
	touch(7, fire_at, true)
	check(not fire.is_pressed(), "disabled button ignores touches")

	print("KNOWLEDGE_CHECK=%s failures=%d" % ["PASS" if failures.is_empty() else "FAIL", failures.size()])
	quit(0 if failures.is_empty() else 1)
