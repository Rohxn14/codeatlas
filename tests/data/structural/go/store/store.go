package store

type Store struct {
	items []string
}

func New() *Store {
	return &Store{}
}

func (s *Store) Add(item string) {
	s.check(item)
	s.items = append(s.items, item)
}

func (s *Store) check(item string) {
}
