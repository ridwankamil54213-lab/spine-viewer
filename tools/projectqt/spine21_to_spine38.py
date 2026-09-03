import argparse
import json
import shutil
from pathlib import Path

from PIL import Image

from spJsonReader import spJsonReader
from spJsonWriter38 import spJsonWriter38
from spAtlas import readAtlasFile
from unpack_atlas_images import unpack_atlas


def read_original_meta(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    skeleton = data.get("skeleton", {})
    return {
        "hash": skeleton.get("hash"),
        "width": skeleton.get("width"),
        "height": skeleton.get("height"),
        "images": skeleton.get("images"),
    }


def copy_sidecar_assets(input_path, output_path):
    copied = []
    copied_sources = set()

    atlas_path = input_path.with_suffix(".atlas")
    if atlas_path.exists():
        dst = output_path.with_suffix(".atlas")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(atlas_path, dst)
        copied.append(dst)
        copied_sources.add(atlas_path.resolve())

        for page in readAtlasFile(str(atlas_path)):
            page_path = atlas_path.parent / page["name"]
            if not page_path.exists():
                continue
            page_dst = output_path.parent / page["name"]
            page_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(page_path, page_dst)
            copied.append(page_dst)
            copied_sources.add(page_path.resolve())

    png_path = input_path.with_suffix(".png")
    if png_path.exists() and png_path.resolve() not in copied_sources:
        dst = output_path.with_suffix(".png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(png_path, dst)
        copied.append(dst)
    return copied


def unpack_copied_atlas(output_path, rotate_direction):
    atlas_path = output_path.with_suffix(".atlas")
    if not atlas_path.exists():
        return []
    return unpack_atlas(atlas_path, output_path.parent / "images", rotate_direction=rotate_direction)


def image_path_for_attachment(output_path, attachment_name, attachment_data):
    image_name = attachment_data.get("path") or attachment_name
    parts = [part for part in image_name.replace("\\", "/").split("/") if part and part != "."]
    if not parts:
        return None
    parts[-1] = parts[-1] + ".png"
    return output_path.parent / "images" / Path(*parts)


def sync_mesh_image_dimensions(output_path, pretty=False):
    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    changed = 0
    for skin in data.get("skins", []):
        for _slot_name, attachments in skin.get("attachments", {}).items():
            for attachment_name, attachment_data in attachments.items():
                if not isinstance(attachment_data, dict) or attachment_data.get("type") != "mesh":
                    continue
                image_path = image_path_for_attachment(output_path, attachment_name, attachment_data)
                if not image_path or not image_path.exists():
                    continue
                with Image.open(image_path) as image:
                    width, height = image.size
                if attachment_data.get("width") != width or attachment_data.get("height") != height:
                    attachment_data["width"] = width
                    attachment_data["height"] = height
                    changed += 1

    if changed:
        if pretty:
            text = json.dumps(data, sort_keys=False, indent=2, separators=(",", ": "), ensure_ascii=False)
        else:
            text = json.dumps(data, sort_keys=False, separators=(",", ":"), ensure_ascii=False)
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    return changed


def set_unpacked_images_path(output_path, pretty=False):
    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    skeleton = data.setdefault("skeleton", {})
    if skeleton.get("images") == "./images/":
        return False

    skeleton["images"] = "./images/"
    if pretty:
        text = json.dumps(data, sort_keys=False, indent=2, separators=(",", ": "), ensure_ascii=False)
    else:
        text = json.dumps(data, sort_keys=False, separators=(",", ":"), ensure_ascii=False)
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def convert_file(input_path, output_path, target_version, pretty=False):
    original_meta = read_original_meta(input_path)
    reader = spJsonReader(False)
    writer = spJsonWriter38(False, targetVersion=target_version)
    skeleton_data = reader.readSkeletonDataFile(str(input_path))
    writer.writeSkeletonDataFile(
        skeleton_data,
        str(output_path),
        pretty=pretty,
        originalMeta=original_meta,
    )
    return skeleton_data


def main():
    parser = argparse.ArgumentParser(description="Convert Spine 2.1.27 JSON to Spine 3.8 JSON layout.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target-version", default="3.8.75")
    parser.add_argument("--copy-assets", action="store_true")
    parser.add_argument("--unpack-images", action="store_true")
    parser.add_argument("--rotate-direction", choices=("cw", "ccw"), default="cw")
    parser.add_argument("--keep-mesh-size", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    skeleton_data = convert_file(args.input, args.output, args.target_version, pretty=args.pretty)
    copied = copy_sidecar_assets(args.input, args.output) if args.copy_assets else []
    unpacked = unpack_copied_atlas(args.output, args.rotate_direction) if args.unpack_images else []
    images_path_updated = set_unpacked_images_path(args.output, pretty=args.pretty) if args.unpack_images else False
    synced_meshes = 0 if args.keep_mesh_size or not args.unpack_images else sync_mesh_image_dimensions(args.output, pretty=args.pretty)

    print(f"source={args.input}")
    print(f"output={args.output}")
    print(f"target_version={args.target_version}")
    print(f"bones={len(skeleton_data['bones'])}")
    print(f"skins={len(skeleton_data['skins'])}")
    print(f"animations={len(skeleton_data['animations'])}")
    for path in copied:
        print(f"copied={path}")
    if unpacked:
        print(f"unpacked_images={len(unpacked)}")
        print(f"images_dir={args.output.parent / 'images'}")
    if synced_meshes:
        print(f"synced_mesh_dimensions={synced_meshes}")
    if images_path_updated:
        print("images_path=./images/")


if __name__ == "__main__":
    main()
