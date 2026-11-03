using Shop.Models;
using Shop.Services;

namespace Shop;

public class Program
{
    public static void Main()
    {
        var service = new UserService();
        var user = new User();
        service.Save(user);
        user.Describe();
    }
}
