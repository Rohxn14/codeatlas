# Greets people by name.
class Greeter
  def initialize(name)
    @name = name
  end

  def greet(times)
    count = times
    message = build(count)
    puts message
    log.info(message)
  end
end
