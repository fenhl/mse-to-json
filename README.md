This is a command-line [Python](https://www.python.org/) script that converts [Magic Set Editor](https://magicseteditor.boards.net/) set files to [MTG JSON](https://mtgjson.com/).

# Usage

Python 3.5 or higher is required.

Run the script from the command line with a single argument specifying which MSE set file to convert. The argument can be `-` to read the set file from standard input. The JSON file will be printed to standard output, use your shell's redirection features if you want to save it to disk instead. Additionally, the following optional arguments are supported:

## Command-line arguments

* `--decode`: If used, instead of generating JSON, the MSE set file is unzipped and its `set` text file is printed to stdout.
* `--set-code=<code>`: The expansion code to use for this set. By default, this is read from the MSE set file.
