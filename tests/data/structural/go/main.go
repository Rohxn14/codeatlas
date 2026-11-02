package main

import (
	"fmt"

	m "example.com/shop/money"
	"example.com/shop/store"
)

func main() {
	s := store.New()
	s.Add("tea")
	fmt.Println(m.Format(5))
	report(s)
}
