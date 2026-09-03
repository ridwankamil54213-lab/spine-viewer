import json
import os

from spJsonWriter import spJsonWriter
from spUtils import (
    SP_ATTACHMENT_MESH,
    SP_ATTACHMENT_SKINNED_MESH,
    findSlotNameByIndex,
)


class spJsonWriter38(spJsonWriter):
    def __init__(self, toRaiseConversionError=True, targetVersion="3.8.75"):
        super().__init__(toRaiseConversionError)
        self.targetVersion = targetVersion

    def writeSkeletonDataFile(self, skeletonData, path, pretty=False, blendProperty=False, originalMeta=None):
        tmp_path = path + ".spine21.tmp"
        super().writeSkeletonDataFile(skeletonData, tmp_path, pretty=pretty, blendProperty=blendProperty)

        with open(tmp_path, "r", encoding="utf-8") as f:
            jsonData = json.load(f)

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        self.convertJsonData(jsonData, skeletonData, originalMeta or {})

        if pretty:
            text = json.dumps(jsonData, sort_keys=False, indent=2, separators=(",", ": "), ensure_ascii=False)
        else:
            text = json.dumps(jsonData, sort_keys=False, separators=(",", ":"), ensure_ascii=False)

        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def convertJsonData(self, jsonData, skeletonData, originalMeta):
        skeleton = jsonData.setdefault("skeleton", {})
        skeleton["spine"] = self.targetVersion

        for key in ("hash", "width", "height", "images"):
            if key in originalMeta and originalMeta[key] is not None:
                skeleton[key] = originalMeta[key]
        if skeleton.get("images", None) is None:
            skeleton.pop("images", None)

        self.restoreMeshNonessential(jsonData, skeletonData)
        self.convertSkins(jsonData)
        self.convertAnimations(jsonData)
        self.convertCurveArrays(jsonData)

    def convertSkins(self, jsonData):
        skins = jsonData.get("skins", {})
        if isinstance(skins, list):
            for skin in skins:
                self.convertAttachments(skin.get("attachments", {}))
            return

        converted = []
        names = list(skins.keys())
        if "default" in names:
            names.remove("default")
            names.insert(0, "default")

        for name in names:
            attachments = skins.get(name, {})
            self.convertAttachments(attachments)
            converted.append({
                "name": name,
                "attachments": attachments,
            })

        jsonData["skins"] = converted

    def restoreMeshNonessential(self, jsonData, skeletonData):
        skins = jsonData.get("skins", {})
        if not isinstance(skins, dict):
            return

        for skin in skeletonData.get("skins", []):
            skinName = skin.get("name")
            jsonSkin = skins.get(skinName)
            if not isinstance(jsonSkin, dict):
                continue

            for slot in skin.get("slots", []):
                slotName = findSlotNameByIndex(slot["slotIndex"], skeletonData["slots"])
                jsonSlot = jsonSkin.get(slotName)
                if not isinstance(jsonSlot, dict):
                    continue

                for attachment in slot.get("attachments", []):
                    if attachment.get("attachmentType") not in (SP_ATTACHMENT_MESH, SP_ATTACHMENT_SKINNED_MESH):
                        continue

                    placeholderName = attachment.get("placeholderName")
                    jsonAttachment = jsonSlot.get(placeholderName)
                    if not isinstance(jsonAttachment, dict):
                        continue

                    if len(attachment.get("edges", [])) > 0:
                        jsonAttachment["edges"] = attachment["edges"]
                    if attachment.get("width", 0) > 0:
                        jsonAttachment["width"] = attachment["width"]
                    if attachment.get("height", 0) > 0:
                        jsonAttachment["height"] = attachment["height"]

    def convertAttachments(self, attachments):
        for slotAttachments in attachments.values():
            if not isinstance(slotAttachments, dict):
                continue
            for attachment in slotAttachments.values():
                if not isinstance(attachment, dict):
                    continue
                if attachment.get("type") in ("skinnedmesh", "weightedmesh"):
                    attachment["type"] = "mesh"

    def convertAnimations(self, jsonData):
        animations = jsonData.get("animations", {})
        for animation in animations.values():
            if not isinstance(animation, dict):
                continue
            if "ffd" in animation:
                animation["deform"] = animation.pop("ffd")
            if "drawOrder" in animation:
                animation["draworder"] = animation.pop("drawOrder")

    def convertCurveArrays(self, obj):
        if isinstance(obj, list):
            for item in obj:
                self.convertCurveArrays(item)
            return

        if not isinstance(obj, dict):
            return

        curve = obj.get("curve")
        if isinstance(curve, list):
            if len(curve) > 0:
                obj["curve"] = curve[0]
            if len(curve) > 1:
                obj["c2"] = curve[1]
            if len(curve) > 2:
                obj["c3"] = curve[2]
            if len(curve) > 3:
                obj["c4"] = curve[3]

        for value in obj.values():
            self.convertCurveArrays(value)
