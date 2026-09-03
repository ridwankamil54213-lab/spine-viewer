
from spUtils import *
import json

class spJsonReader():

    def __init__( self, toRaiseConversionError=True ):
        self.toRaise = toRaiseConversionError

    def getColorFromHexString( self, colorDict, colorString ):
        colorDict["r"] = int( colorString[0:2], 16 ) / 255
        colorDict["g"] = int( colorString[2:4], 16 ) / 255
        colorDict["b"] = int( colorString[4:6], 16 ) / 255
        colorDict["a"] = int( colorString[6:8], 16 ) / 255

    def readAnimation( self, jsonAnimation, animationName, skeletonData ):

        animation = { "name": animationName, "slots": list(), "bones": list(), "ik": list(),
                      "ffd": list(), "drawOrder": list(), "events": list() }

        # Slot timelines
        slots = jsonAnimation.get( "slots", dict() )
        slotsKeyList = list( slots.keys() )
        slotIndexes = list()
        
        for i in range( 0, len( slotsKeyList ) ):
            
            slot = slots[ slotsKeyList[i] ]
            slotIndex = findSlotIndexByName( slotsKeyList[i], skeletonData["slots"] )

            timelineKeyList = list( slot.keys() )
            slotDict = { "slotIndex": slotIndex, "timelines": list() }

            for j in range( 0, len( timelineKeyList ) ):

                timelineType = SP_TIMELINE_COLOR

                if ( timelineKeyList[j].startswith( "color" ) ):
                    timelineType = SP_TIMELINE_COLOR
                    
                elif ( timelineKeyList[j] == "attachment" ):
                    timelineType = SP_TIMELINE_ATTACHMENT

                elif ( timelineKeyList[j] == "twoColor" ):
                    timelineType = SP_TIMELINE_TWOCOLOR

                elif ( timelineKeyList[j] == "shear" ):
                    timelineType = SP_TIMELINE_SHEAR

                else:
                    timelineType = SP_TIMELINE_UNKNOWN
                    if self.toRaise:
                        raise ConversionError( "不可用的timeline类型: " + timelineKeyList[j] )

                frames = slot[ timelineKeyList[j] ]
                timelineDict = { "type": timelineType, "framesCount": list( frames ), "frames": list() }

                if ( timelineType == SP_TIMELINE_COLOR ):

                    for frameIndex in range( 0, len( frames ) ):

                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]

                        frame = { "time": time, "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0,
                                  "curve_type": SP_CURVE_LINEAR, "curves": list() }

                        self.getColorFromHexString( frame, frames[frameIndex]["color"] )

                        curveType = frames[frameIndex].get( "curve", None )
                        if ( curveType == None ):
                            frame["curve_type"] = SP_CURVE_LINEAR
                        elif ( curveType == "stepped" ):
                            frame["curve_type"] = SP_CURVE_STEPPED
                        elif ( type( curveType ) == list ):
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = curveType
                        elif ( type( curveType )) == int or type( curveType ) == float:
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = [ curveType, 0, 0, 1 ]
                            for c in [2,3,4]:
                                if f'c{c}' in frames[frameIndex]:
                                    frame["curves"][c-1] = frames[frameIndex][f'c{c}']
                            
                        timelineDict["frames"].append( frame )

                    slotDict["timelines"].append( timelineDict )

                elif ( timelineType == SP_TIMELINE_ATTACHMENT ):

                    for frameIndex in range( 0, len( frames ) ):

                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]
                        attachmentName = frames[frameIndex]["name"]
                        frame = { "time": time, "attachment_name": attachmentName }
                        timelineDict["frames"].append( frame )

                    slotDict["timelines"].append( timelineDict )

                elif ( timelineType == SP_TIMELINE_TWOCOLOR ):
                    
                    for frameIndex in range( 0, len( frames ) ):

                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]

                        frame = { "time": time, "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0,
                                  "curve_type": SP_CURVE_LINEAR, "curves": list() }

                        self.getColorFromHexString( frame, frames[frameIndex]["light"] )

                        curveType = frames[frameIndex].get( "curve", None )
                        if ( curveType == None ):
                            frame["curve_type"] = SP_CURVE_LINEAR
                        elif ( curveType == "stepped" ):
                            frame["curve_type"] = SP_CURVE_STEPPED
                        elif ( type( curveType ) == list ):
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = curveType
                        elif ( type( curveType )) == int or type( curveType ) == float:
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = [ curveType, 0, 0, 1 ]
                            for c in [2,3,4]:
                                if f'c{c}' in frames[frameIndex]:
                                    frame["curves"][c-1] = frames[frameIndex][f'c{c}']
                            
                        timelineDict["frames"].append( frame )

                    slotDict["timelines"].append( timelineDict )


            animation["slots"].append( slotDict )


        # Bone timelines
        bones = jsonAnimation.get( "bones", dict() )
        bonesKeyList = list( bones.keys() )
        
        for i in range( 0, len( bonesKeyList ) ):
            
            bone = bones[ bonesKeyList[i] ]
            boneIndex = findBoneParentIndexByName( bonesKeyList[i], skeletonData["bones"] )
            timelineKeyList = list( bone.keys() )
            boneDict = { "boneIndex": boneIndex, "timelines": list() }

            for j in range( 0, len( timelineKeyList ) ):
                
                timelineType = SP_TIMELINE_ROTATE
                if ( timelineKeyList[j] == "rotate" ):
                    timelineType = SP_TIMELINE_ROTATE
                elif ( timelineKeyList[j] == "scale" ):
                    timelineType = SP_TIMELINE_SCALE
                elif ( timelineKeyList[j] == "translate" ):
                    timelineType = SP_TIMELINE_TRANSLATE
                elif ( timelineKeyList[j] == "flipX" ):
                    timelineType = SP_TIMELINE_FLIPX
                elif ( timelineKeyList[j] == "flipY" ):
                    timelineType = SP_TIMELINE_FLIPY
                elif ( timelineKeyList[j] == "shear" ):
                    timelineType = SP_TIMELINE_SHEAR
                else:
                    timelineType = SP_TIMELINE_UNKNOWN
                    if self.toRaise:
                        raise ConversionError( "不可用的timeline类型: " + timelineKeyList[j] )

                frames = bone[ timelineKeyList[j] ]
                timelineDict = { "type": timelineType, "framesCount": list( frames ), "frames": list() }

                if ( timelineType == SP_TIMELINE_ROTATE ):

                    for frameIndex in range( 0, len( frames ) ):
                        
                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]
                        angle = frames[frameIndex].get( "angle", 0.0 )
                        frame = { "time": time, "angle": angle, "curve_type": SP_CURVE_LINEAR, "curves": list() }

                        curveType = frames[frameIndex].get( "curve", None )
                        if ( curveType == None ):
                            frame["curve_type"] = SP_CURVE_LINEAR
                        elif ( curveType == "stepped" ):
                            frame["curve_type"] = SP_CURVE_STEPPED
                        elif ( type( curveType ) == list ):
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = curveType
                        elif ( type( curveType )) == int or type( curveType ) == float:
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = [ curveType, 0, 0, 1 ]
                            for c in [2,3,4]:
                                if f'c{c}' in frames[frameIndex]:
                                    frame["curves"][c-1] = frames[frameIndex][f'c{c}']

                        timelineDict["frames"].append( frame )

                    boneDict["timelines"].append( timelineDict )

                elif ( timelineType == SP_TIMELINE_TRANSLATE ):

                    for frameIndex in range( 0, len( frames ) ):
                        
                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]
                        x = frames[frameIndex].get( "x", 0.0 )
                        y = frames[frameIndex].get( "y", 0.0 )
                        frame = { "time": time, "x": x, "y": y, "curve_type": SP_CURVE_LINEAR, "curves": list() }

                        curveType = frames[frameIndex].get( "curve", None )
                        if ( curveType == None ):
                            frame["curve_type"] = SP_CURVE_LINEAR
                        elif ( curveType == "stepped" ):
                            frame["curve_type"] = SP_CURVE_STEPPED
                        elif ( type( curveType ) == list ):
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = curveType
                        elif ( type( curveType )) == int or type( curveType ) == float:
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = [ curveType, 0, 0, 1 ]
                            for c in [2,3,4]:
                                if f'c{c}' in frames[frameIndex]:
                                    frame["curves"][c-1] = frames[frameIndex][f'c{c}']
                            
                        timelineDict["frames"].append( frame )

                    boneDict["timelines"].append( timelineDict )

                elif ( timelineType == SP_TIMELINE_SCALE ):

                    for frameIndex in range( 0, len( frames ) ):
                        
                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]
                        if self.trueVersion >= "3.8.75":
                            x = frames[frameIndex].get( "x", 1.0 )
                            y = frames[frameIndex].get( "y", 1.0 )
                        else:
                            x = frames[frameIndex].get( "x", 0.0 )
                            y = frames[frameIndex].get( "y", 0.0 )
                        frame = { "time": time, "x": x, "y": y, "curve_type": SP_CURVE_LINEAR, "curves": list() }

                        curveType = frames[frameIndex].get( "curve", None )
                        if ( curveType == None ):
                            frame["curve_type"] = SP_CURVE_LINEAR
                        elif ( curveType == "stepped" ):
                            frame["curve_type"] = SP_CURVE_STEPPED
                        elif ( type( curveType ) == list ):
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = curveType
                        elif ( type( curveType )) == int or type( curveType ) == float:
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = [ curveType, 0, 0, 1 ]
                            for c in [2,3,4]:
                                if f'c{c}' in frames[frameIndex]:
                                    frame["curves"][c-1] = frames[frameIndex][f'c{c}']
                            
                        timelineDict["frames"].append( frame )

                    boneDict["timelines"].append( timelineDict )

                elif ( timelineType == SP_TIMELINE_FLIPX ):

                    for frameIndex in range( 0, len( frames ) ):

                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]
                        flip = frames[frameIndex].get( "x", False )

                        frame = { "time": time, "flip": flip }

                        timelineDict["frames"].append( frame )

                    boneDict["timelines"].append( timelineDict )

                elif ( timelineType == SP_TIMELINE_FLIPY ):

                    for frameIndex in range( 0, len( frames ) ):

                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        time = frames[frameIndex]["time"]
                        flip = frames[frameIndex].get( "y", False )

                        frame = { "time": time, "flip": flip }

                        timelineDict["frames"].append( frame )

                    boneDict["timelines"].append( timelineDict )

            animation["bones"].append( boneDict )


        # ik timelines
        iks = jsonAnimation.get( "ik", dict() )
        iksKeyList = list( iks.keys() )
        for i in range( 0, len( iksKeyList ) ):

            ikIndex = findIkConstraintIndexByName( iksKeyList[i], skeletonData["ikConstraints"] )

            frames = iks[ iksKeyList[i] ]

            timelineDict = { "ikConstraintIndex": ikIndex, "framesCount": len( frames ), "frames": list() }

            for frameIndex in range( 0, len( frames ) ):
                
                if "time" not in frames[frameIndex]:
                    frames[frameIndex]["time"] = 0
                time = frames[frameIndex]["time"]
                mix = frames[frameIndex].get( "mix", 1.0 )
                bendPositive = frames[frameIndex].get( "bendPositive", False )

                frame = { "time": time, "mix": mix, "bendPositive": -1, "curve_type": 0, "curves": list() }

                if ( bendPositive ):
                    frame["bendPositive"] = 1

                curveType = frames[frameIndex].get( "curve", None )
                if ( curveType == None ):
                    frame["curve_type"] = SP_CURVE_LINEAR
                elif ( curveType == "stepped" ):
                    frame["curve_type"] = SP_CURVE_STEPPED
                elif ( type( curveType ) == list ):
                    frame["curve_type"] = SP_CURVE_BEZIER
                    frame["curves"] = curveType
                elif ( type( curveType )) == int or type( curveType ) == float:
                    frame["curve_type"] = SP_CURVE_BEZIER
                    frame["curves"] = [ curveType, 0, 0, 1 ]
                    for c in [2,3,4]:
                        if f'c{c}' in frames[frameIndex]:
                            frame["curves"][c-1] = frames[frameIndex][f'c{c}']

                timelineDict["frames"].append( frame )

            animation["ik"].append( timelineDict )


        # FFD (Skin Deform) timelines
        if self.trueVersion >= "3.8.75":
            ffd = jsonAnimation.get( "deform", dict() )
        else:
            ffd = jsonAnimation.get( "ffd", dict() )
        skinsKeyList = list( ffd.keys() )
        for i in range( 0, len( skinsKeyList ) ):

            skinIndex = getSkinIndexByName( skinsKeyList[i], skeletonData["skins"] )
            ffdDict = { "skinIndex": skinIndex, "slots": list() }

            slotsKeyList = list( ffd[ skinsKeyList[i] ].keys() )
            for j in range( 0, len( slotsKeyList ) ):

                slotIndex = findSlotIndexByName( slotsKeyList[j], skeletonData["slots"] )
                slotDict = { "slotIndex": slotIndex, "timelines": list() }

                timelinesKeyList = list( ffd[ skinsKeyList[i] ][ slotsKeyList[j] ].keys() )
                for k in range( 0, len( timelinesKeyList ) ):

                    frames = ffd[ skinsKeyList[i] ][ slotsKeyList[j] ][ timelinesKeyList[k] ]

                    timelineDict = { "attachmentName": timelinesKeyList[k],
                                     "framesCount": len( frames ), "frames": list() }
                    timelineDict["type"] = SP_TIMELINE_FFD
                    
                    for frameIndex in range( 0, len( frames ) ):

                        frame = { "frameVertices": list(), "curve_type": SP_CURVE_LINEAR, "curves": list() }

                        if "time" not in frames[frameIndex]:
                            frames[frameIndex]["time"] = 0
                        frame["time"] = frames[frameIndex]["time"]
                        frame["start"] = frames[frameIndex].get( "offset", 0 )
                        frame["end"] = len( frames[frameIndex].get( "vertices", list() ) )

                        for m in range( 0, len( frames[frameIndex].get( "vertices", list() ) ) ):
                            frame["frameVertices"].append( frames[frameIndex]["vertices"][m] )

                        curveType = frames[frameIndex].get( "curve", None )
                        if ( curveType == None ):
                            frame["curve_type"] = SP_CURVE_LINEAR
                        elif ( curveType == "stepped" ):
                            frame["curve_type"] = SP_CURVE_STEPPED
                        elif ( type( curveType ) == list ):
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = curveType
                        elif ( type( curveType )) == int or type( curveType ) == float:
                            frame["curve_type"] = SP_CURVE_BEZIER
                            frame["curves"] = [ curveType, 0, 0, 1 ]
                            for c in [2,3,4]:
                                if f'c{c}' in frames[frameIndex]:
                                    frame["curves"][c-1] = frames[frameIndex][f'c{c}']

                        timelineDict["frames"].append( frame )

                    slotDict["timelines"].append( timelineDict )

                ffdDict["slots"].append( slotDict )

            animation["ffd"].append( ffdDict )


        # Draw Order timelines
        frames = jsonAnimation.get( "draworder", list() )
        if ( len( frames ) == 0 and self.trueVersion != "3.8.75" ):
            frames = jsonAnimation.get( "drawOrder", list() )

        for frameIndex in range( 0, len( frames ) ):

            frameDict = { "time": 0.0, "offsets": list() }

            # offsets can be omitted
            offsets = {offset["slot"]: offset["offset"] for offset in frames[frameIndex].get( "offsets", list())}
            slotNames = skeletonData["slots"][:]
            newOffsets = [[] for _ in range(len(slotNames))]

            for offsetsName in offsets:
                slotIndex = findSlotIndexByName(offsetsName, slotNames)
                newOffsets[slotIndex + offsets[offsetsName]] = [slotIndex, offsets[offsetsName]]

            newOffsetsIndex = 0
            for iSlot in range(len(slotNames)):
                if slotNames[iSlot]["name"] in offsets.keys():
                    continue
                while newOffsets[newOffsetsIndex]: newOffsetsIndex += 1
                newOffsets[newOffsetsIndex] = [iSlot, newOffsetsIndex - iSlot]

            for iSlot in range(len(slotNames)):
                for iOffset in range(len(newOffsets)):
                    if newOffsets[iOffset][0] == iSlot:
                        if newOffsets[iOffset][1] > 0:
                            frameDict["offsets"].append( { "slotIndex": newOffsets[iOffset][0], "amount": newOffsets[iOffset][1] } )
                        break

            # for i in range( 0, len( offsets ) ):

            #     offsets = frames[frameIndex].get( "offsets", list() )

            #     slotIndex = findSlotIndexByName( offsets[i]["slot"], skeletonData["slots"] )
            #     offset = { "slotIndex": slotIndex, "amount": offsets[i]["offset"] }
            #     frameDict["offsets"].append( offset )

            if "time" not in frames[frameIndex]:
                frames[frameIndex]["time"] = 0
            frameDict["time"] = frames[frameIndex]["time"]

            animation["drawOrder"].append( frameDict )


        # Events timelines
        frames = jsonAnimation.get( "events", list() )
        for i in range( 0, len( frames ) ):

            time = frames[i].get( "time", 0.0 )
            eventIndex = findEventIndexByName( frames[i]["name"], skeletonData["events"] )

            event = { "eventIndex": eventIndex,
                      "intValue": 0,
                      "floatValue": 0.0,
                      "stringValue": None }
            
            event["intValue"] = frames[i].get( "int", skeletonData["events"][eventIndex]["intValue"] )
            event["floatValue"] = frames[i].get( "float", skeletonData["events"][eventIndex]["floatValue"] )
            event["stringValue"] = frames[i].get( "string", skeletonData["events"][eventIndex]["stringValue"] )

            frame = { "time": time, "event": event }
            animation["events"].append( frame )

        return animation


    def readAttachment( self, jsonAttachment, placeholderName ):

        attachment = { "placeholderName": placeholderName }

        attachment["attachmentName"] = jsonAttachment.get( "name", None )

        attachment["attachmentType"] = getAttachmentTypeFromJsonToBinary( jsonAttachment.get( "type", None ) )
        if ( attachment["attachmentType"] == SP_ATTACHMENT_UNKNOWN ):
            if self.toRaise:
                raise ConversionError( "不可用的attachment类型: " + jsonAttachment.get( "type", None ) )
            return None

        if ( attachment["attachmentType"] == SP_ATTACHMENT_REGION ):

            attachment["path"] = jsonAttachment.get( "path", None )

            attachment["x"] = jsonAttachment.get( "x", 0.0 )
            attachment["y"] = jsonAttachment.get( "y", 0.0 )
            attachment["scaleX"] = jsonAttachment.get( "scaleX", 1.0 )
            attachment["scaleY"] = jsonAttachment.get( "scaleY", 1.0 )
            attachment["rotation"] = jsonAttachment.get( "rotation", 0.0 )
            attachment["width"] = jsonAttachment["width"]
            attachment["height"] = jsonAttachment["height"]
            attachment["r"] = 1.0
            attachment["g"] = 1.0
            attachment["b"] = 1.0
            attachment["a"] = 1.0
            self.getColorFromHexString( attachment, jsonAttachment.get( "color", "ffffffff" ) )

        elif ( attachment["attachmentType"] == SP_ATTACHMENT_BOUNDING_BOX ):

            attachment["vertices"] = deflattenVertexList( jsonAttachment["vertices"] )

        elif ( attachment["attachmentType"] == SP_ATTACHMENT_MESH ):
            
            attachment["path"] = jsonAttachment.get( "path", None )

            mesh = attachment

            mesh["regionUVs"] = deflattenVertexList( jsonAttachment["uvs"] )
            mesh["triangles"] = jsonAttachment["triangles"]
            if self.trueVersion >= "3.8.75" and len( jsonAttachment["vertices"] ) > len( jsonAttachment["uvs"] ):
                attachment["attachmentType"] = SP_ATTACHMENT_SKINNED_MESH
                mesh["vertices"] = deflattenWeightedVertexList( jsonAttachment["vertices"] )
            else:
                mesh["vertices"] = deflattenVertexList( jsonAttachment["vertices"] )

            mesh["r"] = 1.0
            mesh["g"] = 1.0
            mesh["b"] = 1.0
            mesh["a"] = 1.0
            self.getColorFromHexString( mesh, jsonAttachment.get( "color", "ffffffff" ) )
            mesh["hullLength"] = jsonAttachment["hull"]

            mesh["edges"] = jsonAttachment.get( "edges", list() )
            mesh["width"] = jsonAttachment.get( "width", 0 )
            mesh["height"] = jsonAttachment.get( "height", 0 )

        elif ( attachment["attachmentType"] == SP_ATTACHMENT_SKINNED_MESH ):

            attachment["path"] = jsonAttachment.get( "path", None )

            mesh = attachment

            mesh["regionUVs"] = deflattenVertexList( jsonAttachment["uvs"] )
            mesh["triangles"] = jsonAttachment["triangles"]
            mesh["vertices"] = deflattenWeightedVertexList( jsonAttachment["vertices"] )

            mesh["r"] = 1.0
            mesh["g"] = 1.0
            mesh["b"] = 1.0
            mesh["a"] = 1.0
            self.getColorFromHexString( mesh, jsonAttachment.get( "color", "ffffffff" ) )
            mesh["hullLength"] = jsonAttachment["hull"]

            mesh["edges"] = jsonAttachment.get( "edges", list() )
            mesh["width"] = jsonAttachment.get( "width", 0 )
            mesh["height"] = jsonAttachment.get( "height", 0 )

        return attachment


    def readSkin( self, jsonSkin, skinName, slots ):

        skin = { "name": skinName, "slots": list() }

        slotKeysList = list( jsonSkin.keys() )
        for i in range( 0, len( slotKeysList ) ):
            slotIndex = findSlotIndexByName( slotKeysList[i], slots )
            slot = { "slotIndex": slotIndex, "attachments": list() }

            attachmentKeysList = list( jsonSkin[ slotKeysList[i] ] )
            for j in range( 0, len( attachmentKeysList ) ):
                attachment = self.readAttachment( jsonSkin[ slotKeysList[i] ][ attachmentKeysList[j] ],
                                                  attachmentKeysList[j] )
                if attachment != None:
                    slot["attachments"].append( attachment )

            skin["slots"].append( slot )

        return skin


    def renameDuplicateKeysInJson( self, orderedPairs ):
        # Reject duplicate keys
        d = {}
        i = 1
        for k, v in orderedPairs:
            if k == "spine":
                self.trueVersion = v
                d[k] = "2.1.27"
                d["width"] = 4096
                d["height"] = 4096
            elif k in ["images", "audio"]:
                continue
            elif k in d:
                if k in ["width", "height"] and self.trueVersion >= "3.8.75" :
                    d[k] = v
                    continue
                else:
                    k = k + "_another_key_with_the_same_name_" + str( i )
                d[k] = v
            else:
               d[k] = v
        return d


    def readSkeletonDataFile( self, path ):
        try:
            file = open( path, 'r', encoding='utf-8' )
            text = file.read()
        except UnicodeDecodeError:
            file = open( path, 'r', encoding='gbk' )
            text = file.read()
        file.close()
        jsonData = json.loads( text, object_pairs_hook=self.renameDuplicateKeysInJson )

        skeletonData = spStoredSkeletonData()

        skeletonData["hash"] = jsonData["skeleton"].get( "hash", None )
        skeletonData["version"] = jsonData["skeleton"].get( "spine", None )
        skeletonData["width"] = jsonData["skeleton"].get( "width", 0.0 )
        skeletonData["height"] = jsonData["skeleton"].get( "height", 0.0 )
        skeletonData["images"] = jsonData["skeleton"].get( "images", None )

        skeletonData["nonessential"] = False # skeletonData["nonessential"]
        if ( skeletonData["images"] != None ):
            skeletonData["nonessential"] = True

        # Bones
        skeletonData["bonesCount"] = len( jsonData["bones"] )

        for i in range( 0, skeletonData["bonesCount"] ):
            
            boneData = dict()
            boneData["name"] = jsonData["bones"][i]["name"]
            if ( jsonData["bones"][i].get( "parent", None ) == None ):
                boneData["parent"] = -1
            else:
                boneData["parent"] = findBoneParentIndexByName( jsonData["bones"][i]["parent"], skeletonData["bones"] )

            boneData["x"] = jsonData["bones"][i].get( "x", 0.0 )
            boneData["y"] = jsonData["bones"][i].get( "y", 0.0 )
            boneData["scaleX"] = jsonData["bones"][i].get( "scaleX", 1.0 )
            boneData["scaleY"] = jsonData["bones"][i].get( "scaleY", 1.0 )
            boneData["rotation"] = jsonData["bones"][i].get( "rotation", 0.0 )
            boneData["length"] = jsonData["bones"][i].get( "length", 0.0 )
            boneData["flipX"] = bool( jsonData["bones"][i].get( "flipX", 0 ) )
            boneData["flipY"] = bool( jsonData["bones"][i].get( "flipY", 0 ) )
            boneData["inheritScale"] = bool( jsonData["bones"][i].get( "inheritScale", 1 ) )
            boneData["inheritRotation"] = bool( jsonData["bones"][i].get( "inheritRotation", 1 ) )
            if ( jsonData["bones"][i].get( "transform", None ) == "noRotationOrReflection" ):
                boneData["inheritRotation"] = 0
            
            color = jsonData["bones"][i].get( "color", "989898ff" )
            if ( color != "989898ff" ):
                skeletonData["nonessential"] = True
                
            self.getColorFromHexString( boneData, color )

            skeletonData["bones"].append( boneData )

        # ik
        ikList = jsonData.get( "ik", list() )
        
        for i in range( 0, len( ikList ) ):
            
            ik = {}
            ik["name"] = ikList[i]["name"]
            
            ik["bones"] = list()
            for n in range( 0, len( ikList[i]["bones"] ) ):
                boneIndex = findBoneIndexByName( ikList[i]["bones"][n], skeletonData["bones"] )
                ik["bones"].append( boneIndex )

            ik["mix"] = ikList[i].get( "mix", 1.0 )
            ik["target"] = findBoneIndexByName( ikList[i]["target"], skeletonData["bones"] )
            
            bendPositive = ikList[i].get( "bendPositive", True )
            if ( bendPositive ):
                ik["bendDirection"] = 1
            else:
                ik["bendDirection"] = -1

            skeletonData["ikConstraints"].append( ik )

        # Slots
        if ( len( jsonData.get( "slots", list() ) ) > 0 ):
            
            for i in range( 0, len( jsonData["slots"] ) ):
                
                slot = {}
                slot["name"] = jsonData["slots"][i]["name"]
                slot["boneData"] = findBoneIndexByName( jsonData["slots"][i]["bone"], skeletonData["bones"] )
                slot["attachmentName"] = jsonData["slots"][i].get( "attachment", None )

                slot["r"] = 1.0
                slot["g"] = 1.0
                slot["b"] = 1.0
                slot["a"] = 1.0
                if ( jsonData["slots"][i].get( "color", "ffffffff" ) != "ffffffff" ):
                    self.getColorFromHexString( slot, jsonData["slots"][i]["color"] )

                slot["additiveBlending"] = jsonData["slots"][i].get( "additive", False )

                # SkeletonViewer expects "additive" (bool)
                # some 2.1.27 jsons show it as "blend" (str) though
                # for now check both
                if ( not slot["additiveBlending"] ):
                    if ( jsonData["slots"][i].get( "blend", "normal" ) == "additive" ):
                        slot["additiveBlending"] = True

                skeletonData["slots"].append( slot )

        # Default skin
        if type( jsonData["skins"] ) == list:
            changedJsonData = {}
            for i in range( 0, len( jsonData["skins"] ) ):
                changedJsonData[jsonData["skins"][i]["name"]] = jsonData["skins"][i]["attachments"]
            jsonData["skins"] = changedJsonData
        skinsKeyList = list( jsonData["skins"].keys() )
        for i in range( 0, len( skinsKeyList ) ):
            skin = self.readSkin( jsonData["skins"][skinsKeyList[i]], skinsKeyList[i], skeletonData["slots"] )
            skeletonData["skins"].append( skin )

        # Events
        eventsKeyList = list( jsonData.get( "events", dict() ).keys() )
        if ( len( eventsKeyList ) > 0 ):
            for i in range( 0, len( eventsKeyList ) ):
                
                eventData = { "name": eventsKeyList[i] }
                eventData["intValue"] = jsonData["events"][ eventsKeyList[i] ].get( "int", 0 )
                eventData["floatValue"] = jsonData["events"][ eventsKeyList[i] ].get( "float", 0.0 )
                eventData["stringValue"] = jsonData["events"][ eventsKeyList[i] ].get( "string", None )
                skeletonData["events"].append( eventData )

        # Animations
        animationsKeyList = list( jsonData.get( "animations", dict() ).keys() )
        if ( len( animationsKeyList ) > 0 ):
            for i in range( 0, len( animationsKeyList ) ):
                animation = self.readAnimation( jsonData["animations"][animationsKeyList[i]],
                                                animationsKeyList[i], skeletonData )
                skeletonData["animations"].append( animation )
        
        return skeletonData
