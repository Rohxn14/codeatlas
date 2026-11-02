package store

import "testing"

func TestAdd(t *testing.T) {
	s := New()
	s.Add("tea")
}
