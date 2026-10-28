extends SceneTree
## Navigation contract for the ScreenRouter recipe.

const ScreenRouter := preload("res://kit/screen_router.gd")

var failures: Array[String] = []


func _initialize() -> void:
	_run.call_deferred()


func check(condition: bool, message: String) -> void:
	if condition:
		print("ok: " + message)
	else:
		failures.append(message)
		printerr("FAIL: " + message)


func make_scene(scene_name: String) -> PackedScene:
	var node := Node.new()
	node.name = scene_name
	var packed := PackedScene.new()
	packed.pack(node)
	node.free()
	return packed


func count(screen: String) -> int:
	return root.get_children().filter(func(child): return String(child.name) == screen).size()


func screen_nodes(router: Node) -> int:
	return root.get_children().filter(func(child): return child != router).size()


func _run() -> void:
	InputMap.add_action(&"fire")
	var router: Node = ScreenRouter.new()
	root.add_child(router)
	for screen in ["main_menu", "game", "pause", "game_over", "settings"]:
		router.register(StringName(screen), make_scene(screen))

	router.goto(&"main_menu")
	check(router.current_name == &"main_menu" and count("main_menu") == 1, "starts at main menu")
	check(router.back() == false, "back at home is unhandled (caller may quit)")

	router.goto(&"settings")
	check(router.back() and router.current_name == &"main_menu", "back from settings returns home")
	check(count("settings") == 0, "settings screen removed")

	router.goto(&"game")
	check(count("main_menu") == 0 and count("game") == 1, "menu -> game leaves exactly one screen")

	var first_game: Node = router.current
	Input.action_press(&"fire")
	router.restart()
	check(router.current != first_game and count("game") == 1, "restart re-instances game once")
	check(not Input.is_action_pressed(&"fire"), "transition releases held actions")

	router.open_overlay(&"pause")
	check(router.is_paused() and router.top_overlay() == &"pause", "pause overlay pauses tree")
	check(router.overlays[0].process_mode == Node.PROCESS_MODE_ALWAYS, "overlay keeps processing while paused")
	check(router.back() and not router.is_paused() and router.overlays.is_empty(), "back closes pause and resumes")

	check(router.back() and router.top_overlay() == &"pause", "back in gameplay opens pause instead of leaving")
	router.close_overlay()

	router.notification(Node.NOTIFICATION_APPLICATION_FOCUS_OUT)
	check(router.top_overlay() == &"pause" and router.is_paused(), "focus loss in gameplay auto-pauses")
	router.notification(Node.NOTIFICATION_APPLICATION_FOCUS_OUT)
	check(router.overlays.size() == 1, "repeated focus loss does not stack pause overlays")

	router.goto(&"game_over")
	check(router.overlays.is_empty() and not router.is_paused(), "screen change clears overlays and unpauses")
	check(count("pause") == 0 and count("game") == 0, "no stale game/pause nodes after game over")
	check(screen_nodes(router) == 1, "exactly one screen node in the tree")
	router.notification(Node.NOTIFICATION_APPLICATION_FOCUS_OUT)
	check(router.overlays.is_empty(), "focus loss outside gameplay does not pause")

	router.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
	check(router.current_name == &"main_menu", "Android back from game over returns home")

	router.goto(&"game")
	router.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
	check(router.top_overlay() == &"pause", "Android back in gameplay opens pause")
	router.goto(&"main_menu")

	print("KNOWLEDGE_CHECK=%s failures=%d" % ["PASS" if failures.is_empty() else "FAIL", failures.size()])
	quit(0 if failures.is_empty() else 1)
