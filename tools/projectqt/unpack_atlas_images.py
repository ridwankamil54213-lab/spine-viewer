import argparse
from pathlib import Path

from PIL import Image

from spAtlas import readAtlasFile


def normalize_region_path(name):
    parts = [part for part in name.replace("\\", "/").split("/") if part and part != "."]
    if not parts:
        raise ValueError(f"Invalid atlas region name: {name!r}")
    parts[-1] = parts[-1] + ".png"
    return Path(*parts)


def unpack_region(page_image, region, rotate_direction):
    x = int(region["x"])
    y = int(region["y"])
    width = int(region["width"])
    height = int(region["height"])

    if region.get("rotate"):
        image = page_image.crop((x, y, x + height, y + width))
        if rotate_direction == "cw":
            image = image.transpose(Image.Transpose.ROTATE_270)
        elif rotate_direction == "ccw":
            image = image.transpose(Image.Transpose.ROTATE_90)
        else:
            raise ValueError(f"Unsupported rotate direction: {rotate_direction}")
    else:
        image = page_image.crop((x, y, x + width, y + height))

    return image


def unpack_atlas(atlas_path, output_dir, rotate_direction="cw", overwrite=True):
    atlas_path = Path(atlas_path)
    output_dir = Path(output_dir)
    pages = readAtlasFile(str(atlas_path))
    written = []

    for page in pages:
        page_path = atlas_path.parent / page["name"]
        if not page_path.exists():
            raise FileNotFoundError(f"Atlas page image not found: {page_path}")

        with Image.open(page_path) as page_image:
            page_image.load()
            for region in page.get("regionSections", []):
                output_path = output_dir / normalize_region_path(region["name"])
                if output_path.exists() and not overwrite:
                    continue

                output_path.parent.mkdir(parents=True, exist_ok=True)
                unpacked = unpack_region(page_image, region, rotate_direction)
                unpacked.save(output_path)
                written.append(output_path)

    return written


def main():
    parser = argparse.ArgumentParser(description="Unpack libGDX/Spine atlas pages into individual image files.")
    parser.add_argument("atlas", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--rotate-direction", choices=("cw", "ccw"), default="cw")
    parser.add_argument("--no-overwrite", action="store_true")
    args = parser.parse_args()

    output_dir = args.out or (args.atlas.parent / "images")
    written = unpack_atlas(
        args.atlas,
        output_dir,
        rotate_direction=args.rotate_direction,
        overwrite=not args.no_overwrite,
    )

    print(f"atlas={args.atlas}")
    print(f"output_dir={output_dir}")
    print(f"images={len(written)}")
    for path in written[:20]:
        print(f"written={path}")
    if len(written) > 20:
        print(f"written_more={len(written) - 20}")


if __name__ == "__main__":
    main()
