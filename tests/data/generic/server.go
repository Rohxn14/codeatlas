package server

import "fmt"

// Store saves users.
type Store interface {
	Save(name string) error
}

type Server struct {
	store Store
}

func NewServer(s Store) *Server {
	return &Server{store: s}
}

func (s *Server) Start() error {
	fmt.Println("starting")
	return s.store.Save("boot")
}

func helper() {
	NewServer(nil)
}
