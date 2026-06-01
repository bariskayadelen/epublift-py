import os
import zipfile
from PIL import Image, ImageDraw

def create_dummy_images():
    os.makedirs('temp_epub_src/OEBPS/images', exist_ok=True)
    
    # Create cover.jpg
    img_cover = Image.new('RGB', (600, 800), color='#2c3e50')
    d = ImageDraw.Draw(img_cover)
    d.text((50, 350), "SAMPLE BOOK COVER", fill='#f1c40f')
    d.text((50, 400), "EPUB 2 Format", fill='#ffffff')
    img_cover.save('temp_epub_src/OEBPS/images/cover.jpg', 'JPEG')
    
    # Create logo.png
    img_logo = Image.new('RGBA', (200, 200), color=(0, 0, 0, 0))
    d_logo = ImageDraw.Draw(img_logo)
    d_logo.ellipse([20, 20, 180, 180], fill='#e74c3c')
    d_logo.text((60, 90), "LOGO", fill='#ffffff')
    img_logo.save('temp_epub_src/OEBPS/images/logo.png', 'PNG')

def create_text_files():
    # mimetype
    with open('temp_epub_src/mimetype', 'w') as f:
        f.write('application/epub+zip')
        
    # container.xml
    os.makedirs('temp_epub_src/META-INF', exist_ok=True)
    with open('temp_epub_src/META-INF/container.xml', 'w') as f:
        f.write('''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>''')

    # styles.css
    with open('temp_epub_src/OEBPS/styles.css', 'w') as f:
        f.write('''body {
    font-family: sans-serif;
    margin: 1em;
    color: #333333;
}
.logo-container {
    text-align: center;
    background-image: url('images/logo.png');
    background-repeat: no-repeat;
    height: 200px;
    width: 200px;
    margin: auto;
}
''')

    # chapter1.html
    with open('temp_epub_src/OEBPS/chapter1.html', 'w') as f:
        f.write('''<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>Chapter 1: The Beginning</title>
    <link rel="stylesheet" type="text/css" href="styles.css"/>
</head>
<body>
    <h1>Chapter 1: The Beginning</h1>
    <p>This is a paragraph with a cover image below.</p>
    <p><img src="images/cover.jpg" alt="Cover Image" style="max-width: 100%;"/></p>
</body>
</html>''')

    # chapter2.html
    with open('temp_epub_src/OEBPS/chapter2.html', 'w') as f:
        f.write('''<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>Chapter 2: The Next Step</title>
    <link rel="stylesheet" type="text/css" href="styles.css"/>
</head>
<body>
    <h1>Chapter 2: The Next Step</h1>
    <p>This is chapter 2. It references the logo in CSS and also inline:</p>
    <div class="logo-container"></div>
    <p><img src="images/logo.png" alt="Logo" /></p>
</body>
</html>''')

    # toc.ncx
    with open('temp_epub_src/OEBPS/toc.ncx', 'w') as f:
        f.write('''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:12345678-1234-5678-1234-567812345678"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>Test EPUB 2 Book</text>
  </docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel>
        <text>Chapter 1: The Beginning</text>
      </navLabel>
      <content src="chapter1.html"/>
    </navPoint>
    <navPoint id="navPoint-2" playOrder="2">
      <navLabel>
        <text>Chapter 2: The Next Step</text>
      </navLabel>
      <content src="chapter2.html"/>
    </navPoint>
  </navMap>
</ncx>''')

    # content.opf
    with open('temp_epub_src/OEBPS/content.opf', 'w') as f:
        f.write('''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="BookId" opf:scheme="UUID">urn:uuid:12345678-1234-5678-1234-567812345678</dc:identifier>
    <dc:title>Test EPUB 2 Book</dc:title>
    <dc:creator opf:role="aut">Jane Doe</dc:creator>
    <dc:language>en</dc:language>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="style" href="styles.css" media-type="text/css"/>
    <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg"/>
    <item id="logo-image" href="images/logo.png" media-type="image/png"/>
    <item id="chapter1" href="chapter1.html" media-type="text/html"/>
    <item id="chapter2" href="chapter2.html" media-type="text/html"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chapter1"/>
    <itemref idref="chapter2"/>
  </spine>
  <guide>
    <reference type="cover" title="Cover Page" href="chapter1.html"/>
  </guide>
</package>''')

def package_epub(output_filename):
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Mimetype must be first and uncompressed
        zf.write('temp_epub_src/mimetype', 'mimetype', compress_type=zipfile.ZIP_STORED)
        
        # Add other files
        for root, dirs, files in os.walk('temp_epub_src'):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, 'temp_epub_src')
                if arcname == 'mimetype':
                    continue
                zf.write(file_path, arcname)
                
    # Clean up temp folder
    import shutil
    shutil.rmtree('temp_epub_src')
    print(f"Sample EPUB file created successfully: {output_filename}")

if __name__ == '__main__':
    create_dummy_images()
    create_text_files()
    package_epub('sample_epub2.epub')
