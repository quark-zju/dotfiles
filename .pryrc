Y = ->p{->f{f[f]}[->g{p[->*n{g[g][*n]}]}]} unless defined? Y

[ 'prime',
  'fileutils',
  'active_support/time',
  'active_support/core_ext',
  'awesome_print',
  # 'interactive_editor', (pry has builtin 'edit')
  'term/ansicolor',
  'digest'
].each do |m|
  begin
    require m
  rescue LoadError => e
    warn e
  end
end

if defined? Term::ANSIColor
  class String
    include Term::ANSIColor
  end
end

class String
  def sha1
    Digest::SHA1.hexdigest(self)
  end
  def sha2
    Digest::SHA2.hexdigest(self)
  end
  def md5
    Digest::MD5.hexdigest(self)
  end
end

if RUBY_ENGINE == 'jruby'
  System = java.lang.System
end

# vim: set ft=ruby:
