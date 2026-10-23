extends Node3D
## PoC scene: frame the imported crate and rotate it so runtime checks observe a state change.

@export var spin_speed: float = 0.6

@onready var prop: Node3D = $Prop_Crate
@onready var camera: Camera3D = $Camera3D


func _ready() -> void:
	camera.look_at(Vector3(0.0, 0.55, 0.0))


func _process(delta: float) -> void:
	prop.rotate_y(spin_speed * delta)
