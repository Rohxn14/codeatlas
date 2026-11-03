<?php
namespace Shop\Tests;

use Shop\Services\UserService;

class UserServiceTest
{
    public function testSave()
    {
        $service = new UserService();
        $service->save(null);
    }
}
