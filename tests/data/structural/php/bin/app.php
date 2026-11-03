<?php
use Shop\Models\{User, Post as P};
use Shop\Services\UserService;

$user = User::find(1);
$post = P::find(2);
$service = new UserService();
$service->save($user);
