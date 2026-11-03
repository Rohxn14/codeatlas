module Shop
  class User
    def self.build
      new
    end

    def describe
      helper
      name
    end

    def name
      "ada"
    end

    def helper
    end
  end
end
