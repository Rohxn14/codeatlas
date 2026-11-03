using System;

namespace Shop.Services
{
    using Shop.Models;
    using Shop.Util;
    using static Shop.Util.Money;
    using Json = System.Text.Json.JsonSerializer;

    public class UserService
    {
        public void Save(User user)
        {
            Validate(user);
            var slug = Format.Slug(user.Name);
            Json.Serialize(user);
            Show(3);
            Console.WriteLine(slug);
        }

        private void Validate(User user)
        {
        }
    }
}
