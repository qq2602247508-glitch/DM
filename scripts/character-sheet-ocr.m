#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) {
            fprintf(stderr, "usage: character-sheet-ocr IMAGE\n");
            return 2;
        }
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSImage *image = [[NSImage alloc] initWithContentsOfFile:path];
        if (image == nil) {
            fprintf(stderr, "cannot read image\n");
            return 3;
        }
        NSRect rect = NSMakeRect(0, 0, image.size.width, image.size.height);
        CGImageRef cgImage = [image CGImageForProposedRect:&rect context:nil hints:nil];
        if (cgImage == nil) {
            fprintf(stderr, "cannot decode image\n");
            return 4;
        }
        VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
        request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        request.usesLanguageCorrection = YES;
        request.recognitionLanguages = @[@"zh-Hans", @"en-US"];
        VNImageRequestHandler *handler =
            [[VNImageRequestHandler alloc] initWithCGImage:cgImage options:@{}];
        NSError *error = nil;
        if (![handler performRequests:@[request] error:&error]) {
            fprintf(stderr, "OCR failed: %s\n", error.localizedDescription.UTF8String);
            return 5;
        }
        for (VNRecognizedTextObservation *observation in request.results) {
            VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
            if (candidate != nil) {
                printf("%s\n", candidate.string.UTF8String);
            }
        }
    }
    return 0;
}
