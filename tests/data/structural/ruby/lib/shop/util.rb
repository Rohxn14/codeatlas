module Shop
  module Util
    def self.slug(text)
      clean(text)
      text.tr(" ", "-")
    end

    def self.clean(text)
      text.strip
    end
  end
end
