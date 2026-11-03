<?php
namespace Shop\Models;

class User
{
    public function describe()
    {
        return "user " . $this->name();
    }

    public function name()
    {
        return "ada";
    }

    public static function find($id)
    {
        return new User();
    }
}
