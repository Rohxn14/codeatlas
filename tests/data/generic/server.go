package server

import "fmt"

// Store saves users.
type Store interface {
	Save(name string) error
}

// Server handles requests.
type Server struct {
	store Store
}

// NewServer builds a Server.
func NewServer(store Store) *Server {
	return &Server{store: store}
}

// Handle saves one user and logs it.
func (s *Server) Handle(name string) error {
	fmt.Println("saving", name)
	return s.store.Save(name)
}

func main() {
	srv := NewServer(nil)
	srv.Handle("ada")
}
