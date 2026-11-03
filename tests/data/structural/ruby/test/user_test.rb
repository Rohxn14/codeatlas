require "minitest/autorun"
require_relative "../lib/shop"

class UserTest < Minitest::Test
  def test_boot
    Shop.boot
  end
end
