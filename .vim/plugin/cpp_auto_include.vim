if exists("g:loaded_auto_cpp_include")
    finish
endif

if !has("ruby")
    echohl ErrorMsg
    echon "Sorry, auto_cpp_include requires ruby support."
    finish
endif

let g:loaded_auto_cpp_include = "true"

autocmd BufWritePre /tmp/**.cc :ruby auto_cpp_include

ruby << EOF

def curlines
    $curbuf.length.times.map { |i| $curbuf[i + 1] }
end

def uniq_append(i, content)
  return false if ($curbuf.length >= i+1 && $curbuf[i+1] == content) 
  cursor = $curwin.cursor
  $curbuf.append(i, content)
  $curwin.cursor = [cursor.first+1,cursor.last] if cursor.first >= i
  content
end

def uniq_remove(i, content)
  if i.nil?
    # find i first
    $curbuf.length.times do |id|
      if $curbuf[id + 1] == content
        i = id + 1
        break
      end
    end
    return if i.nil?
  end

  while true
    return if $curbuf[i] != content || i >= $curbuf.length
    cursor = $curwin.cursor
    $curbuf.delete(i)
    $curwin.cursor = [[1,cursor.first-1].max,cursor.last] if cursor.first >= i
  end
end

USING_STD = 'using namespace std;'
def auto_cpp_include
  return if $curbuf.length > 1000

  begin
  lines = curlines
  includes = curlines.select { |l| l =~ /#\s*include/ }
  content = curlines.select { |l| ! (l =~ /#\s*include/) }.join("\n")

  File.open('/tmp/debug.txt', 'w') do |f|
    f.puts "includes = #{includes}"
    f.puts "content = #{content}"
  end

  # common headers
  use_std = false
  { :iostream => ['cerr', 'cout', 'cin'],
    :sstream => ['stringstream'],
    :vector => [/vector\s*</],
    :map => [/map\s*</],
    :set => [/set\s*</],
    :cstdio => ['scanf', 'FILE', 'puts', 'printf'],
    :cassert => ['assert'],
    :cstring => ['memset', 'strlen', 'strerror', /strn?cmp/, 'strcat', 'memcmp'],
    :cstdlib => ['abs', 'EXIT_', 'NULL', 'exit', 'ato', 'free', 'malloc', 'rand', /qsort\s*\(/],
    :string => ['string'],
    :typeinfo => ['typeid']
  }.each do |header, keywords|
    header = "<#{header}>"
    has_keyword = keywords.any? { |word| content[word] }
    has_header = includes.any? { |l| l.include? header }
    use_std = true if has_keyword && !header.start_with?('<c')

    if has_keyword && !has_header
      # add include
      last_include_line = includes.last
      if last_include_line.nil?
        uniq_append(0, "#include #{header}")
      else
        $curbuf.length.times do |i|
          if $curbuf[i + 1] == last_include_line
            uniq_append(i + 1, "#include #{header}")
            break
          end
        end
      end
    elsif !has_keyword && has_header
      # remove include
      uniq_remove(nil, includes.detect { |l| l.include? header })
    end
  end

  # append empty line to last #include
  includes = curlines.zip(1..$curbuf.length).select { |l| l.first =~ /#\s*include/ }

  if includes.empty?
    uniq_remove(1, '')
  else
    uniq_append(includes.last.last, '')
  end

  # using namespace std
  has_std = content[USING_STD]

  if use_std && !has_std
    unless includes.empty?
      uniq_append(includes.last.last+1, USING_STD) 
      uniq_append(includes.last.last+2, '')
    end
  elsif !use_std && has_std
    uniq_remove(nil, USING_STD)
  end

  rescue => ex
    File.open("/tmp/ex.txt", 'w') do |f|
      f.puts ex
      f.puts ex.backtrace.join("\n")
    end
    throw RuntimeError(ex)
  end
end

EOF
