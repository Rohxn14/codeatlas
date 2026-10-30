module example.com/shop/api

go 1.22

require (
	example.com/shop/lib v0.0.0 // indirect
	github.com/google/uuid v1.6.0
)

replace example.com/shop/lib => ../lib
