// Block namespaces, nested and side by side: this file declares Shop.Text and
// Shop.Labels (the outer Shop only wraps them).
namespace Shop
{
    namespace Text
    {
        public static class Pad
        {
            public static string Left(string text)
            {
                return " " + text;
            }
        }
    }

    namespace Labels
    {
        public static class Label
        {
            public static string Make(string text)
            {
                return "[" + text + "]";
            }
        }
    }
}
