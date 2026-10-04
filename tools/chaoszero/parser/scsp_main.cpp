// Convert a Yuna-engine .scsp file to Spine JSON (stdout).
#include "SCSPParser.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>
int main(int argc, char** argv){
    if (argc < 2){ std::cerr << "usage: scsp2json file.scsp\n"; return 2; }
    std::ifstream f(argv[1], std::ios::binary);
    if (!f){ std::cerr << "cannot open " << argv[1] << "\n"; return 1; }
    std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    try {
        std::cout << SCSPParser::ConvertToJson(d);
    } catch (const std::exception& e) {
        std::cerr << "ERR " << e.what() << "\n"; return 3;
    }
    return 0;
}
