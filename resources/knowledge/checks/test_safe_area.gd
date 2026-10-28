extends SceneTree
## Safe-area mapping from screen pixels into viewport coordinates.

const SafeAreaMargin := preload("res://kit/safe_area_margin.gd")

var failures: Array[String] = []


func _initialize() -> void:
	_run.call_deferred()


func check(condition: bool, message: String) -> void:
	if condition:
		print("ok: " + message)
	else:
		failures.append(message)
		printerr("FAIL: " + message)


func margins(container: MarginContainer) -> Array:
	return [container.get_theme_constant(&"margin_left"), container.get_theme_constant(&"margin_top"),
			container.get_theme_constant(&"margin_right"), container.get_theme_constant(&"margin_bottom")]


func _run() -> void:
	# Headless defaults to a 100x100 window; test at a phone portrait size.
	root.size = Vector2i(720, 1280)
	var container: MarginContainer = SafeAreaMargin.new()
	root.add_child(container)
	await process_frame
	var viewport := root.get_visible_rect().size

	# A 2x-density screen with a 100 px notch on top and 60 px gesture bar.
	var screen := viewport * 2.0
	container.apply_safe_rect(Rect2(0, 100, screen.x, screen.y - 160), screen)
	check(margins(container) == [0, 50, 0, 30], "portrait notch maps to viewport units %s" % [margins(container)])

	# Landscape cutout on the left.
	container.apply_safe_rect(Rect2(88, 0, screen.x - 88, screen.y), screen)
	check(margins(container) == [44, 0, 0, 0], "landscape cutout on the left %s" % [margins(container)])

	container.extra_margin = 8
	container.apply_safe_rect(Rect2(), screen)
	check(margins(container) == [8, 8, 8, 8], "no safe area reported -> extra margin only")

	container.apply_safe_rect(Rect2(0, 0, 10, 10), Vector2.ZERO)
	check(margins(container) == [8, 8, 8, 8], "zero screen size is ignored safely")

	print("KNOWLEDGE_CHECK=%s failures=%d" % ["PASS" if failures.is_empty() else "FAIL", failures.size()])
	quit(0 if failures.is_empty() else 1)
