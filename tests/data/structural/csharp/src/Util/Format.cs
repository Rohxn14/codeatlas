namespace Shop.Util;

public static class Format
{
    public static string Upper(string text)
    {
        return text.ToUpper();
    }

    public static string Slug(string text)
    {
        return text.Replace(" ", "-");
    }
}
