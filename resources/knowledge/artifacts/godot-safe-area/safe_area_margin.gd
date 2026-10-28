class_name SafeAreaMargin
extends MarginContainer
## Keeps HUD and menu content out of notches, rounded corners and system bars.
##
## Put HUD/menu content inside this container and anchor it full-rect. It maps
## DisplayServer's safe area (screen pixels) into viewport coordinates, so it
## stays correct with any stretch mode and on rotation.

@export var extra_margin := 0


func _ready() -> void:
	get_viewport().size_changed.connect(apply)
	apply()


func apply() -> void:
	apply_safe_rect(Rect2(DisplayServer.get_display_safe_area()),
			Vector2(DisplayServer.screen_get_size()))


## Separated from apply() so the mapping can be tested without a device.
func apply_safe_rect(safe: Rect2, screen: Vector2) -> void:
	var margins := [extra_margin, extra_margin, extra_margin, extra_margin]
	if screen.x > 0.0 and screen.y > 0.0 and safe.has_area():
		var scale := get_viewport_rect().size / screen
		margins = [
			int(ceil(safe.position.x * scale.x)) + extra_margin,
			int(ceil(safe.position.y * scale.y)) + extra_margin,
			int(ceil((screen.x - safe.end.x) * scale.x)) + extra_margin,
			int(ceil((screen.y - safe.end.y) * scale.y)) + extra_margin,
		]
	add_theme_constant_override(&"margin_left", margins[0])
	add_theme_constant_override(&"margin_top", margins[1])
	add_theme_constant_override(&"margin_right", margins[2])
	add_theme_constant_override(&"margin_bottom", margins[3])
