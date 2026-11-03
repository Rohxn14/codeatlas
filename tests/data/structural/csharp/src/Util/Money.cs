namespace Shop.Util;

public static class Money
{
    public static string Show(int cents)
    {
        return Format.Upper("usd " + cents);
    }
}
