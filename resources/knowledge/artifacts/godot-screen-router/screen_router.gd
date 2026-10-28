extends Node
## Single owner of screen changes, overlays, pause and back navigation.
##
## Register as an autoload named ScreenRouter. Screens never call
## change_scene_to_* themselves; they call ScreenRouter.goto(&"name").
## Every transition releases held input actions so a finger lifted during a
## transition cannot leave the player walking or firing on the next screen.
##
## Android back: set application/config/quit_on_go_back=false so the back
## gesture reaches back() instead of quitting.

signal screen_changed(screen: StringName)
signal overlay_changed(overlay: StringName)

## Screen that back() returns to and that the app starts on.
@export var home: StringName = &"main_menu"
## Overlay opened automatically when a gameplay screen loses focus.
@export var pause_overlay: StringName = &"pause"
## Screens on which focus loss should pause the game.
@export var gameplay_screens: Array[StringName] = [&"game"]

var current_name: StringName = &""
var current: Node
var overlays: Array[Node] = []
var host: Node

var _screens: Dictionary = {}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	if host == null:
		host = get_tree().root


## `scene` is a res:// path or a PackedScene.
func register(screen: StringName, scene: Variant) -> void:
	_screens[screen] = scene


func has_screen(screen: StringName) -> bool:
	return _screens.has(screen)


func goto(screen: StringName) -> Node:
	var instance := _instantiate(screen)
	_close_all_overlays()
	get_tree().paused = false
	release_all_actions()
	if is_instance_valid(current):
		# Leave the tree now, not at frame end, so the old and new screens
		# never coexist (duplicate HUDs, double signal handlers).
		current.get_parent().remove_child(current)
		current.queue_free()
	current = instance
	current_name = screen
	host.add_child(current)
	screen_changed.emit(screen)
	return current


func restart() -> Node:
	return goto(current_name)


func open_overlay(screen: StringName, pause := true) -> Node:
	var overlay := _instantiate(screen)
	overlay.process_mode = Node.PROCESS_MODE_ALWAYS
	overlay.set_meta(&"router_screen", screen)
	release_all_actions()
	host.add_child(overlay)
	overlays.push_back(overlay)
	if pause:
		get_tree().paused = true
	overlay_changed.emit(screen)
	return overlay


func close_overlay() -> void:
	if overlays.is_empty():
		return
	var overlay: Node = overlays.pop_back()
	overlay.get_parent().remove_child(overlay)
	overlay.queue_free()
	release_all_actions()
	if overlays.is_empty():
		get_tree().paused = false
	overlay_changed.emit(top_overlay())


func top_overlay() -> StringName:
	return overlays.back().get_meta(&"router_screen") if not overlays.is_empty() else &""


func is_paused() -> bool:
	return get_tree().paused


## Back button / Escape: close an overlay, else return home. Returns false
## when already home so the caller may quit.
func back() -> bool:
	if not overlays.is_empty():
		close_overlay()
		return true
	if current_name in gameplay_screens and has_screen(pause_overlay):
		open_overlay(pause_overlay)
		return true
	if current_name != home and has_screen(home):
		goto(home)
		return true
	return false


func release_all_actions() -> void:
	for action in InputMap.get_actions():
		if Input.is_action_pressed(action):
			Input.action_release(action)


func _notification(what: int) -> void:
	match what:
		NOTIFICATION_WM_GO_BACK_REQUEST:
			back()
		NOTIFICATION_APPLICATION_FOCUS_OUT, NOTIFICATION_APPLICATION_PAUSED:
			release_all_actions()
			if current_name in gameplay_screens and overlays.is_empty() and has_screen(pause_overlay):
				open_overlay(pause_overlay)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed(&"ui_cancel"):
		if back():
			get_viewport().set_input_as_handled()


func _close_all_overlays() -> void:
	while not overlays.is_empty():
		var overlay: Node = overlays.pop_back()
		overlay.get_parent().remove_child(overlay)
		overlay.queue_free()


func _instantiate(screen: StringName) -> Node:
	assert(_screens.has(screen), "unknown screen: %s" % screen)
	var scene: Variant = _screens[screen]
	var packed: PackedScene = load(scene) if scene is String else scene
	return packed.instantiate()
