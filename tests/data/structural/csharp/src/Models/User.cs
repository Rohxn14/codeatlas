namespace Shop.Models;

public class User
{
    public string Name = "";

    public string Describe()
    {
        return "user " + Name;
    }
}
