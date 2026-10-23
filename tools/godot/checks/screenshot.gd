extends SceneTree
## Visual gate helper: run graphically, render real frames, save a PNG.
## Env: SCENE_PATH, SCREENSHOT_PATH, SCREENSHOT_FRAMES
## Must NOT be run with --headless (the dummy renderer cannot produce an image).

var frame_limit := 20
var frames_processed := 0
var capturing := false
var finished := false
var scene_instance: Node = null


func _env(name: String, fallback: String = "") -> String:
	var value := OS.get_environment(name)
	return value if value != "" else fallback


func _initialize() -> void:
	frame_limit = maxi(3, int(_env("SCREENSHOT_FRAMES", "20")))
	var scene_path := _env("SCENE_PATH",
		str(ProjectSettings.get_setting("application/run/main_scene", "")))
	var screenshot_path := _env("SCREENSHOT_PATH")
	if screenshot_path == "":
		_fail("SCREENSHOT_PATH is required")
		return
	if scene_path == "":
		_fail("no scene configured")
		return

	var packed := load(scene_path)
	if not (packed is PackedScene):
		_fail("failed to load PackedScene: %s" % scene_path)
		return
	scene_instance = (packed as PackedScene).instantiate()
	if scene_instance == null:
		_fail("instantiate() returned null")
		return
	root.add_child(scene_instance)
	process_frame.connect(_on_process_frame)


func _fail(message: String) -> void:
	if finished:
		return
	finished = true
	push_error(message)
	print("SCREENSHOT=FAIL")
	print(JSON.stringify({"status": "FAIL", "error": message}, "  "))
	quit(1)


func _on_process_frame() -> void:
	if finished:
		return
	frames_processed += 1
	if frames_processed >= frame_limit and not capturing:
		capturing = true
		_capture()


func _capture() -> void:
	await RenderingServer.frame_post_draw
	var path := _env("SCREENSHOT_PATH")
	var image: Image = root.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("viewport image is empty (was the process headless?)")
		return

	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var error := image.save_png(path)
	if error != OK:
		_fail("save_png failed with error %d: %s" % [error, path])
		return

	var width := image.get_width()
	var height := image.get_height()
	var step := maxi(1, int(mini(width, height) / 48))
	var unique_colors := {}
	var min_luminance := 1.0
	var max_luminance := 0.0
	for y in range(0, height, step):
		for x in range(0, width, step):
			var color := image.get_pixel(x, y)
			unique_colors[color.to_html(false)] = true
			var luminance := color.get_luminance()
			min_luminance = minf(min_luminance, luminance)
			max_luminance = maxf(max_luminance, luminance)

	var status := "PASS" if unique_colors.size() >= 4 else "FAIL"
	var report := {
		"status": status,
		"path": path,
		"width": width,
		"height": height,
		"scenes_in_bundle": scene_instance != null,
		"unique_sampled_colors": unique_colors.size(),
		"sample_step_px": step,
		"min_luminance": min_luminance,
		"max_luminance": max_luminance,
		"frames_processed": frames_processed,
		"generated_at_utc": Time.get_datetime_string_from_system(true),
	}
	print(JSON.stringify(report, "  "))
	print("SCREENSHOT=%s" % status)
	finished = true
	quit(0 if status == "PASS" else 1)
