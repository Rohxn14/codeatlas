use money_fmt::Formatter;

#[test]
fn formats_whole_numbers() {
    let text = Formatter::new().format(5);
    assert_eq!(text, "5");
}
