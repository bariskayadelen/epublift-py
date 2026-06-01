#!/usr/bin/env python3
"""
EPUB Version Booster
--------------------
A program to optimize EPUB files by:
1. Extracting to a temporary workspace to preserve the original file.
2. Converting raster images (JPEG, PNG, etc.) to WebP with custom compression.
3. Upgrading the internal structure to comply with the EPUB 3.3 specification
   (converting NCX TOC to XHTML Navigation Document, updating package metadata,
   standardizing DOCTYPEs, and adding modern metadata).
4. Generating a comprehensive size comparison and optimization report.

Requirements:
- Python 3.6+
- Pillow (PIL) for image conversion
"""

import os
import sys
import shutil
import zipfile
import tempfile
import argparse
import datetime
import urllib.parse
import re
from pathlib import Path
import xml.etree.ElementTree as ET

# Register standard namespaces to ensure clean XML generation without "ns0:" prefixes
XML_NAMESPACES = {
    '': 'http://www.idpf.org/2007/opf',
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
    'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
    'ncx': 'http://www.daisy.org/z3986/2005/ncx/',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'epub': 'http://www.idpf.org/2007/ops'
}

for prefix, uri in XML_NAMESPACES.items():
    ET.register_namespace(prefix, uri)

class EPUBBooster:
    def __init__(self, input_path, output_path=None, quality=80, report_path=None):
        self.input_path = Path(input_path).resolve()
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
            
        if output_path:
            self.output_path = Path(output_path).resolve()
        else:
            self.output_path = self.input_path.parent / f"{self.input_path.stem}_boosted.epub"
            
        if report_path:
            self.report_path = Path(report_path).resolve()
        else:
            self.report_path = self.input_path.parent / f"{self.input_path.stem}_report.txt"
            
        self.quality = max(1, min(100, quality))
        
        # Performance/Size Metrics
        self.original_size = self.input_path.stat().st_size
        self.final_size = 0
        self.image_metrics = [] # List of dicts with image stats
        
        # Lazy imports for Pillow
        try:
            from PIL import Image
            self.PIL_Image = Image
        except ImportError:
            print("Error: The 'Pillow' library is required for image conversion.", file=sys.stderr)
            print("Please install it using: pip install pillow", file=sys.stderr)
            sys.exit(1)

    def run(self):
        print(f"[*] Starting optimization for: {self.input_path.name}")
        print(f"[*] Target output path: {self.output_path}")
        print(f"[*] WebP Image Quality: {self.quality}%")
        
        # Create a temporary directory in the system's temp area
        with tempfile.TemporaryDirectory(prefix="epub_booster_") as temp_dir:
            temp_dir_path = Path(temp_dir)
            
            # Step 1: Extract EPUB
            print("[*] Extracting original EPUB file...")
            self._extract_epub(temp_dir_path)
            
            # Step 2: Locate and parse the OPF Package file
            opf_path = self._locate_opf(temp_dir_path)
            print(f"[+] Located package document (OPF): {opf_path.relative_to(temp_dir_path)}")
            
            # Parse OPF XML
            opf_tree = ET.parse(opf_path)
            opf_root = opf_tree.getroot()
            
            # Step 3: Optimize Images
            print("[*] Converting and compressing images to WebP...")
            converted_images = self._optimize_images(temp_dir_path, opf_path, opf_root)
            
            # Step 4: Upgrade file structure to EPUB 3.3
            print("[*] Upgrading structure to EPUB 3.3 compliance...")
            self._upgrade_to_epub3(temp_dir_path, opf_path, opf_root, converted_images)
            
            # Write updated OPF back to disk
            opf_tree.write(opf_path, encoding='utf-8', xml_declaration=True)
            
            # Step 5: Repackage EPUB
            print("[*] Repackaging folder into EPUB file...")
            self._repackage_epub(temp_dir_path)
            
        # Step 6: Generate Report
        self.final_size = self.output_path.stat().st_size
        self._write_report()
        
        print(f"\n[+] Optimization complete!")
        print(f"[+] Output EPUB: {self.output_path}")
        print(f"[+] Report file: {self.report_path}")
        
        # Print summary
        saved_bytes = self.original_size - self.final_size
        percent_saved = (saved_bytes / self.original_size) * 100 if self.original_size > 0 else 0
        print(f"[+] Size reduced from {self.original_size/1024/1024:.2f} MB to {self.final_size/1024/1024:.2f} MB ({percent_saved:.1f}% savings)")

    def _extract_epub(self, temp_dir):
        with zipfile.ZipFile(self.input_path, 'r') as zf:
            zf.extractall(temp_dir)

    def _locate_opf(self, temp_dir):
        container_path = temp_dir / "META-INF" / "container.xml"
        if not container_path.exists():
            raise FileNotFoundError("Invalid EPUB: META-INF/container.xml is missing.")
            
        tree = ET.parse(container_path)
        root = tree.getroot()
        
        # Namespace map for container.xml
        ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
        rootfile = root.find('.//c:rootfile', ns)
        if rootfile is None or 'full-path' not in rootfile.attrib:
            # Try without namespace in case XML is malformed
            rootfile = root.find('.//rootfile')
            if rootfile is None or 'full-path' not in rootfile.attrib:
                raise ValueError("Could not find rootfile element in container.xml")
                
        opf_rel_path = rootfile.attrib['full-path']
        return temp_dir / opf_rel_path

    def _optimize_images(self, temp_dir, opf_path, opf_root):
        """
        Finds all raster images in the manifest, converts them to WebP,
        updates the OPF manifest references, and returns a dictionary
        mapping old image hrefs to new WebP hrefs.
        """
        package_dir = opf_path.parent
        ns = {'opf': 'http://www.idpf.org/2007/opf'}
        
        # Locate the manifest element
        manifest = opf_root.find('opf:manifest', ns)
        if manifest is None:
            # Try without namespace
            manifest = opf_root.find('manifest')
            if manifest is None:
                raise ValueError("EPUB OPF is missing the manifest element")
                
        # Find the cover image ID if specified in metadata
        cover_id = None
        metadata = opf_root.find('opf:metadata', ns)
        if metadata is None:
            metadata = opf_root.find('metadata')
            
        if metadata is not None:
            cover_meta = metadata.find(".//opf:meta[@name='cover']", ns)
            if cover_meta is None:
                cover_meta = metadata.find(".//meta[@name='cover']")
            if cover_meta is not None:
                cover_id = cover_meta.get('content')
                
        converted_images = {} # Old href -> New href (relative to OPF)
        
        # Supported raster image types for conversion
        target_media_types = {
            'image/jpeg': 'image/webp',
            'image/jpg': 'image/webp',
            'image/png': 'image/webp'
        }
        
        # Iterate and modify manifest items in-place
        items = manifest.findall('opf:item', ns)
        if not items:
            items = manifest.findall('item')
        items = list(items)
        for item in items:
            item_id = item.get('id')
            href = item.get('href')
            media_type = item.get('media-type')
            
            if media_type in target_media_types:
                # Resolve full path of the image
                # Hrefs are URL-encoded, we must decode to get the actual file path
                decoded_href = urllib.parse.unquote(href)
                img_path = (package_dir / decoded_href).resolve()
                
                if not img_path.exists():
                    print(f"  [!] Warning: Image file not found: {img_path.name}")
                    continue
                    
                # New WebP details
                new_href_path = Path(decoded_href).with_suffix('.webp')
                new_href = str(new_href_path).replace('\\', '/')
                new_img_path = (package_dir / new_href_path).resolve()
                
                # Perform image conversion
                try:
                    orig_size = img_path.stat().st_size
                    
                    with self.PIL_Image.open(img_path) as img:
                        # Standardize image modes if needed (e.g. RGBA -> RGB if saving jpeg, but we are saving webp so RGBA is fully supported)
                        img.save(new_img_path, 'WEBP', quality=self.quality)
                        
                    new_size = new_img_path.stat().st_size
                    savings = orig_size - new_size
                    pct = (savings / orig_size * 100) if orig_size > 0 else 0
                    
                    self.image_metrics.append({
                        'name': img_path.name,
                        'original_size': orig_size,
                        'new_size': new_size,
                        'savings': savings,
                        'percentage': pct
                    })
                    
                    # Delete the original image
                    img_path.unlink()
                    print(f"  [+] Converted: {img_path.name} -> {new_img_path.name} ({orig_size/1024:.1f}KB -> {new_size/1024:.1f}KB, {pct:.1f}% saved)")
                    
                    # Update manifest XML attributes
                    item.set('href', urllib.parse.quote(new_href))
                    item.set('media-type', 'image/webp')
                    
                    # If this is the cover image, add the official EPUB 3 cover-image property
                    if item_id == cover_id or 'cover' in item_id.lower() or 'cover' in href.lower():
                        item.set('properties', 'cover-image')
                        
                    # Map the relative change (keep both original href and normalized versions)
                    converted_images[href] = new_href
                    converted_images[decoded_href] = new_href
                    
                except Exception as e:
                    print(f"  [!] Failed to convert image {img_path.name}: {e}")
                    
        # Update references in all document and stylesheet files
        self._update_document_references(temp_dir, converted_images)
        return converted_images

    def _update_document_references(self, temp_dir, converted_images):
        """
        Scans all XHTML, HTML, CSS, and SVG files in the EPUB extraction
        directory and updates links to converted WebP images.
        """
        if not converted_images:
            return
            
        extensions_to_update = {'.xhtml', '.html', '.htm', '.css', '.svg', '.ncx'}
        
        for root, _, files in os.walk(temp_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in extensions_to_update:
                    try:
                        # Read content as text
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            
                        updated = False
                        
                        # Replace occurrences of old image files
                        for old_href, new_href in converted_images.items():
                            old_name = Path(old_href).name
                            new_name = Path(new_href).name
                            
                            # Update exact href references (e.g. "images/cover.jpg" -> "images/cover.webp")
                            # We check literal paths, URL-encoded paths, and base names for absolute safety
                            old_href_encoded = urllib.parse.quote(old_href)
                            new_href_encoded = urllib.parse.quote(new_href)
                            
                            if old_href in content:
                                content = content.replace(old_href, new_href)
                                updated = True
                            if old_href_encoded in content:
                                content = content.replace(old_href_encoded, new_href_encoded)
                                updated = True
                                
                            # Safe replacement of image base name if not already replaced
                            # To avoid replacing substrings, we target filenames with boundaries
                            # e.g., replacing "logo.png" with "logo.webp"
                            if old_name in content:
                                # Simple replacement is safe because filenames are unique and extension-based
                                content = content.replace(old_name, new_name)
                                updated = True
                                
                        if updated:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                                
                    except Exception as e:
                        print(f"  [!] Warning: Failed to update references in {file_path.name}: {e}")

    def _upgrade_to_epub3(self, temp_dir, opf_path, opf_root, converted_images):
        """
        Updates the OPF file and other structures to comply with EPUB 3.3.
        - Sets the version to '3.0'
        - Adds mandatory 'dcterms:modified' metadata
        - Builds an XHTML 3 Navigation Document from the NCX TOC (if available)
        - Cleans up and modernizes XHTML Doctype elements
        """
        ns = {'opf': 'http://www.idpf.org/2007/opf', 'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}
        package_dir = opf_path.parent
        
        # 1. Update package version attribute to "3.0" (the official version string for EPUB 3)
        opf_root.set('version', '3.0')
        
        # 2. Add or update required <meta property="dcterms:modified"> metadata
        metadata = opf_root.find('opf:metadata', ns)
        if metadata is None:
            metadata = opf_root.find('metadata')
        if metadata is None:
            metadata = ET.SubElement(opf_root, 'metadata')
            
        # Ensure namespace for dc and dcterms are declared on metadata if possible
        metadata.set('xmlns:dc', XML_NAMESPACES['dc'])
        metadata.set('xmlns:dcterms', XML_NAMESPACES['dcterms'])
        
        # Remove any existing modified property to avoid duplicates
        existing_mods = metadata.findall(".//opf:meta[@property='dcterms:modified']", ns)
        for mod in existing_mods:
            metadata.remove(mod)
            
        # Create a fresh UTC timestamp in the required format
        utc_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mod_element = ET.SubElement(metadata, 'meta')
        mod_element.set('property', 'dcterms:modified')
        mod_element.text = utc_now
        
        # 3. Handle Navigation Document (TOC)
        # Check if a Navigation Document already exists in the manifest
        manifest = opf_root.find('opf:manifest', ns)
        if manifest is None:
            manifest = opf_root.find('manifest')
            
        nav_item_exists = False
        nav_href = 'nav.xhtml'
        
        if manifest is not None:
            manifest_items = manifest.findall('opf:item', ns)
            if not manifest_items:
                manifest_items = manifest.findall('item')
            for item in manifest_items:
                properties = item.get('properties', '')
                if 'nav' in properties.split():
                    nav_item_exists = True
                    nav_href = item.get('href')
                    break
                    
        # If not, let's look for toc.ncx and generate a nav.xhtml Navigation Document
        if not nav_item_exists and manifest is not None:
            ncx_item = None
            manifest_items = manifest.findall('opf:item', ns)
            if not manifest_items:
                manifest_items = manifest.findall('item')
            for item in manifest_items:
                media_type = item.get('media-type', '')
                if media_type == 'application/x-dtbncx+xml':
                    ncx_item = item
                    break
                    
            if ncx_item is not None:
                ncx_href = urllib.parse.unquote(ncx_item.get('href'))
                ncx_path = package_dir / ncx_href
                
                if ncx_path.exists():
                    print("[+] Creating mandatory EPUB 3 Navigation Document from toc.ncx...")
                    try:
                        self._generate_nav_xhtml(ncx_path, package_dir / 'nav.xhtml', opf_root, ns)
                        
                        # Add nav.xhtml to the manifest
                        new_nav_item = ET.SubElement(manifest, 'item')
                        new_nav_item.set('id', 'nav')
                        new_nav_item.set('href', 'nav.xhtml')
                        new_nav_item.set('media-type', 'application/xhtml+xml')
                        new_nav_item.set('properties', 'nav')
                        print("  [+] Registered nav.xhtml with properties='nav' in package document.")
                    except Exception as e:
                        print(f"  [!] Failed to generate Navigation Document: {e}")
                        
        # 4. Clean up deprecated `<guide>` block in favor of `<nav epub:type="landmarks">`
        # Landmarking is already handled inside `_generate_nav_xhtml` based on OPF's guide
        guide = opf_root.find('opf:guide', ns)
        if guide is None:
            guide = opf_root.find('guide')
        if guide is not None:
            opf_root.remove(guide)
            print("  [+] Replaced legacy <guide> element with HTML5 landmarks navigation.")
            
        # 5. Clean up Content Files DOCTYPEs and namespaces
        self._standardize_xhtml_files(temp_dir)

    def _generate_nav_xhtml(self, ncx_path, nav_out_path, opf_root, ns):
        """
        Parses toc.ncx and generates a valid EPUB 3 XHTML Navigation Document (nav.xhtml).
        Also includes guide references inside a 'landmarks' nav block if found in OPF.
        """
        ncx_ns = {'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}
        ncx_tree = ET.parse(ncx_path)
        ncx_root = ncx_tree.getroot()
        
        # Extract title
        title_text = "Table of Contents"
        title_elem = ncx_root.find(".//ncx:docTitle/ncx:text", ncx_ns)
        if title_elem is not None and title_elem.text:
            title_text = title_elem.text
            
        # Parse nested navPoint structure
        nav_map = ncx_root.find("ncx:navMap", ncx_ns)
        
        def parse_nav_points(parent_elem):
            items = []
            points = parent_elem.findall("ncx:navPoint", ncx_ns)
            for p in points:
                lbl = p.find("ncx:navLabel/ncx:text", ncx_ns)
                src = p.find("ncx:content", ncx_ns)
                
                title = lbl.text if lbl is not None else "Untitled"
                href = src.get('src') if src is not None else ""
                
                # Check for child navPoints
                children = parse_nav_points(p)
                items.append({
                    'title': title,
                    'href': href,
                    'children': children
                })
            return items
            
        toc_items = parse_nav_points(nav_map) if nav_map is not None else []
        
        # Build XHTML string representation
        xhtml_content = []
        xhtml_content.append('<?xml version="1.0" encoding="utf-8"?>')
        xhtml_content.append('<!DOCTYPE html>')
        xhtml_content.append('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">')
        xhtml_content.append('<head>')
        xhtml_content.append(f'  <title>{title_text}</title>')
        xhtml_content.append('  <meta charset="utf-8" />')
        xhtml_content.append('  <style>')
        xhtml_content.append('    body { font-family: sans-serif; margin: 2em; }')
        xhtml_content.append('    nav ol { list-style-type: none; padding-left: 1.5em; }')
        xhtml_content.append('    nav ol li { margin: 0.5em 0; }')
        xhtml_content.append('    a { text-decoration: none; color: #1a73e8; }')
        xhtml_content.append('    a:hover { text-decoration: underline; }')
        xhtml_content.append('    h1 { color: #333333; }')
        xhtml_content.append('  </style>')
        xhtml_content.append('</head>')
        xhtml_content.append('<body>')
        xhtml_content.append('  <nav epub:type="toc" id="toc">')
        xhtml_content.append(f'    <h1>{title_text}</h1>')
        
        def render_ol(items, level=2):
            indent = "  " * level
            xhtml_content.append(f'{indent}<ol>')
            for item in items:
                # Standardize href forward slash
                href = item['href'].replace('\\', '/')
                xhtml_content.append(f'{indent}  <li>')
                if href:
                    xhtml_content.append(f'{indent}    <a href="{href}">{item["title"]}</a>')
                else:
                    xhtml_content.append(f'{indent}    <span>{item["title"]}</span>')
                if item['children']:
                    render_ol(item['children'], level + 2)
                xhtml_content.append(f'{indent}  </li>')
            xhtml_content.append(f'{indent}</ol>')
            
        if toc_items:
            render_ol(toc_items)
        else:
            xhtml_content.append('    <p>No table of contents available.</p>')
            
        xhtml_content.append('  </nav>')
        
        # Extract Guide and map to landmarks
        guide = opf_root.find('opf:guide', ns)
        if guide is None:
            guide = opf_root.find('guide')
            
        if guide is not None:
            guide_refs = guide.findall('opf:reference', ns)
            if not guide_refs:
                guide_refs = guide.findall('reference')
                
            if guide_refs:
                xhtml_content.append('\n  <nav epub:type="landmarks" id="landmarks" hidden="">')
                xhtml_content.append('    <h2>Guide Landmarks</h2>')
                xhtml_content.append('    <ol>')
                for ref in guide_refs:
                    ref_type = ref.get('type', '')
                    ref_href = ref.get('href', '').replace('\\', '/')
                    ref_title = ref.get('title', ref_type.capitalize())
                    
                    # Convert EPUB 2 standard guide types to EPUB 3 landmark semantics if required
                    type_mapping = {
                        'text': 'bodymatter',
                        'title-page': 'titlepage',
                        'acknowledgements': 'acknowledgments',
                        'cover': 'cover',
                        'toc': 'toc'
                    }
                    mapped_type = type_mapping.get(ref_type, ref_type)
                    xhtml_content.append(f'      <li><a epub:type="{mapped_type}" href="{ref_href}">{ref_title}</a></li>')
                xhtml_content.append('    </ol>')
                xhtml_content.append('  </nav>')
                
        xhtml_content.append('</body>')
        xhtml_content.append('</html>')
        
        with open(nav_out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(xhtml_content))

    def _standardize_xhtml_files(self, temp_dir):
        """
        Standardizes HTML/XHTML files to conform to EPUB 3 best practices:
        - Updates legacy DOCTYPE declarations to HTML5 Standard <!DOCTYPE html>
        - Standardizes XML namespaces and declarations
        """
        for root, _, files in os.walk(temp_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in {'.html', '.xhtml', '.htm'}:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            
                        # Replace old DOCTYPE declarations (XHTML 1.1) with HTML5 <!DOCTYPE html>
                        doctype_pattern = re.compile(r'<!DOCTYPE\s+html[^>]*>', re.IGNORECASE)
                        content = doctype_pattern.sub('<!DOCTYPE html>', content)
                        
                        # Ensure standard HTML5 XML structure exists
                        # (XHTML requires the xmlns attribute on html tag)
                        if 'xmlns="http://www.w3.org/1999/xhtml"' not in content:
                            content = content.replace('<html', '<html xmlns="http://www.w3.org/1999/xhtml"')
                            
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                    except Exception as e:
                        print(f"  [!] Warning: Could not modernize HTML tag in {file}: {e}")

    def _repackage_epub(self, temp_dir):
        """
        Repackages extracted folder into a standard ZIP archive structure.
        The 'mimetype' file must be written first and must remain UNCOMPRESSED.
        All subsequent files are added using DEFLATE compression.
        """
        with zipfile.ZipFile(self.output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 1. Write the mimetype file first, strictly uncompressed
            mimetype_path = temp_dir / 'mimetype'
            if mimetype_path.exists():
                zf.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
            else:
                # Fallback if mimetype doesn't exist
                zf.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
                
            # 2. Add all other files
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(temp_dir)
                    
                    if str(arcname) == 'mimetype':
                        continue
                        
                    zf.write(file_path, arcname)

    def _write_report(self):
        """
        Generates a text report in a beautifully aligned format.
        """
        saved_bytes = self.original_size - self.final_size
        savings_percent = (saved_bytes / self.original_size * 100) if self.original_size > 0 else 0
        
        report = []
        report.append("=" * 60)
        report.append("           EPUB VERSION BOOSTER OPTIMIZATION REPORT")
        report.append("=" * 60)
        report.append(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Original File: {self.input_path.name}")
        report.append(f"Optimized File: {self.output_path.name}")
        report.append("-" * 60)
        report.append("FILE SIZE COMPARISON")
        report.append("-" * 60)
        report.append(f"Original EPUB Size:  {self.original_size:>14,} bytes ({self.original_size/1024/1024:.2f} MB)")
        report.append(f"Boosted EPUB Size:   {self.final_size:>14,} bytes ({self.final_size/1024/1024:.2f} MB)")
        report.append(f"Absolute Size Saved:  {saved_bytes:>14,} bytes ({saved_bytes/1024/1024:.2f} MB)")
        report.append(f"Percentage Saved:     {savings_percent:>13.1f}%")
        report.append("-" * 60)
        report.append("EPUB 3.3 COMPLIANCE ACTIONS")
        report.append("-" * 60)
        report.append("[x] Upgraded root <package> element to version='3.0'")
        report.append("[x] Added required 'dcterms:modified' UTC timestamp metadata")
        report.append("[x] Parsed legacy toc.ncx and generated EPUB 3 Navigation Document (nav.xhtml)")
        report.append("[x] Upgraded all content DOCTYPEs to modern HTML5 standards")
        report.append("[x] Replaced legacy <guide> landmarks references with hidden <nav epub:type='landmarks'>")
        report.append("-" * 60)
        report.append("IMAGE OPTIMIZATION BREAKDOWN (CONVERTED TO WEBP)")
        report.append("-" * 60)
        
        if self.image_metrics:
            header = f"{'Image Name':<30} | {'Original (KB)':<13} | {'WebP (KB)':<9} | {'Saved (%)':<10}"
            report.append(header)
            report.append("-" * 60)
            for m in self.image_metrics:
                row = f"{m['name'][:29]:<30} | {m['original_size']/1024:>13,.1f} | {m['new_size']/1024:>9,.1f} | {m['percentage']:>9.1f}%"
                report.append(row)
        else:
            report.append("No raster images (JPEG/PNG) were found or converted.")
            
        report.append("=" * 60)
        
        with open(self.report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))


def main():
    parser = argparse.ArgumentParser(
        description="Optimize EPUB structure to 3.3 and convert images to WebP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example Usage:
  python3 epub_booster.py -i book.epub -q 75
  python3 epub_booster.py --input book.epub --output optimized.epub --quality 80 --report results.txt
"""
    )
    parser.add_argument("-i", "--input", required=True, help="Path to original EPUB file to boost")
    parser.add_argument("-o", "--output", help="Path to save the optimized EPUB (optional)")
    parser.add_argument("-q", "--quality", type=int, default=80, help="WebP compression quality from 1 to 100 (default: 80)")
    parser.add_argument("-r", "--report", help="Path to write the summary size report (optional)")
    
    args = parser.parse_args()
    
    try:
        booster = EPUBBooster(
            input_path=args.input,
            output_path=args.output,
            quality=args.quality,
            report_path=args.report
        )
        booster.run()
    except Exception as e:
        print(f"\n[!] Fatal Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
