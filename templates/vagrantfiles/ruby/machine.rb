require_relative './config.rb'

class Machine
  attr_reader :name, :type, :hostname, :ip, :memory, :box, :url

  LINUX   = 1
  WINDOWS = 2

  def initialize(
    name:,
    type:,
    hostname:,
    ip:,
    memory: nil,
    box: nil,
    url: nil,
    config: nil
  )
    @name = name
    @type = type
    @ip = ip
    @hostname = hostname

    @memory = (memory.nil?) ? config.getMemory(name) : memory
    @box = (box.nil? or box.empty?) ? config.getBox(type, name) : box
    @url = (url.nil? or url.empty?) ? config.getBoxURL(name) : url
  end
end
