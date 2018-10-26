require 'json'
require_relative './machine.rb'

class Hash
  def dig(*path)
    path.inject(self) do |location, key|
      location.respond_to?(:keys) ? location[key] : nil
    end
  end
end

class Config
  def initialize(file, linux_box, windows_box)
    begin
      @config = JSON.parse(File.read(file))
    rescue Errno::ENOENT => e
      @config = {}
    end

    @linux_box = linux_box
    @windows_box = windows_box
  end

  def getMemory(name)
    value = @config.dig("boxes", name, "memory")

    if value.nil?
      return 0
    end

    return value
  end
  
  def getBox(type, name)
    value = @config.dig("boxes", name, "name")

    if value.nil? or value.empty?
      case type
      when Machine::LINUX
        value = @linux_box
      when Machine::WINDOWS
        value = @windows_box
      end
    end

    return value
  end

  def getBoxURL(name)
    value = @config.dig("boxes", name, "url")

    if value.nil? or value.empty?
      return nil
    end

    return value
  end

  def getFolders(type, env_var)
    if ENV.has_key?("SSSD_TEST_SUITE_BOX")
      if ENV["SSSD_TEST_SUITE_BOX"] == "yes"
        return {}
      end
    end

    folders = {}
    value = @config.dig("folders", type)
    if not value.nil?
      value.each do |folder|
        host = folder["host"]
        guest = folder["guest"]

        next if host.nil? or host.empty?
        next if guest.nil? or guest.empty?

        folders[host] = guest
      end
    end

    if ENV.has_key?(env_var)
      ENV[env_var].split(" ").each do |mount|
         host, guest = mount.split(":")
         folders[host] = guest
      end
    end

    return folders
  end
end
