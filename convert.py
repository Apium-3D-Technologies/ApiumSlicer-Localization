from polib import pofile

# Takes an .po file as an input and makes a copy of given file, where
# the translation for each text is equal to the original text. The tool
# was used to create an english translation the change "PrusaSlicer" to
# "ApiumSlicer" via the Poedit software.

# Path to your source .po file
file_path = "target.po"

# Ouput file name
output = "result.po"

po = pofile(file_path)

for entry in po:
    entry.msgstr = entry.msgid  # Set msgid as msgstr

po.save(output)

print("Done...")
