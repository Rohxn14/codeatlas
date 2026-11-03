<?php
namespace Shop\Util;

class Format
{
    public static function slug($text)
    {
        return money(1) . str_replace(" ", "-", $text);
    }
}
