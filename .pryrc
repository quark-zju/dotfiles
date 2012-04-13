begin
  Y = ->p{->f{f[f]}[->g{p[->*n{g[g][*n]}]}]}

  # activesupport for datetime
  require 'prime'
  require 'fileutils'
  require 'active_support/time'
  require 'active_support/core_ext/string'
  require 'awesome_print'
  require 'interactive_editor'
  require 'term/ansicolor'

  class String
    include Term::ANSIColor
  end

rescue LoadError => err
end

# vim: set ft=ruby:
