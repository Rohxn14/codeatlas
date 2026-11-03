<?php
namespace Shop\Models;

class Post
{
    public function describe()
    {
        return "post";
    }

    public static function find($id)
    {
        return new Post();
    }
}
