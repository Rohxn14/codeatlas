using Shop.Services;

namespace Shop.Tests;

public class UserServiceTests
{
    public void TestSave()
    {
        var service = new UserService();
        service.Save(null);
    }
}
