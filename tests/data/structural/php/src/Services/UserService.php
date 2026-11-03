<?php
namespace Shop\Services;

use Shop\Models\User;
use Shop\Util\Format as F;
use Illuminate\Support\Str;
use function Shop\Util\money;

class UserService
{
    public function save(User $user)
    {
        $this->validate($user);
        $slug = F::slug($user->name());
        Str::slug($slug);
        money(3);
        $user->describe();
        User::find(1);
    }

    private function validate($user)
    {
    }
}
