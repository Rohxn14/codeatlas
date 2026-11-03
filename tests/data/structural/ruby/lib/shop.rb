require "json"
require_relative "shop/user"
require_relative "shop/util"

module Shop
  def self.boot
    user = User.build
    puts Util.slug("a b")
    JSON.generate(user.describe)
  end
end
